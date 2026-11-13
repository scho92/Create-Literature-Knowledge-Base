"""
Hybrid Graph+Vector RAG query tool for the vascular-chip literature graph
(lean v2 schema: platform type, cell source, generation mode, architecture,
perfusion type, ECM/matrix).

Modes:
  categories                         List the controlled-vocabulary values currently in the graph.
  filter    [--platform-type ...] [--cell-source ...] [--generation-mode ...]
            [--architecture ...] [--perfusion-type ...] [--ecm ...]
                                      Exact graph filter over one or more category axes. No LLM call.
  search "<question>" [--top-k N] [filters as above]
                                      Embed the question, vector-search EvidenceChunk nodes
                                      (optionally pre-filtered by category), print ranked hits.
  ask "<question>" [--top-k N] [filters as above]
                                      Same retrieval as `search`, then ask a local LLM (Ollama) to
                                      draft a cited paragraph (by paper_id + DOI) from the retrieved
                                      evidence only.

Examples:
  python3 query_rag.py categories
  python3 query_rag.py filter --cell-source "Direct reprogramming / transdifferentiation (non-pluripotent)"
  python3 query_rag.py filter --architecture "Self-organized / self-assembled (no scaffold)" \\
                               --perfusion-type "In vitro only"
  python3 query_rag.py filter --generation-mode "EC and SMC co-generated in one protocol"
  python3 query_rag.py ask "What is the longest reported in vitro perfusion duration for self-assembled vascular tubes?"

Embeddings and generation both run locally via Ollama (no API key / cost) —
requires `ollama serve` running, with `nomic-embed-text` and `llama3.1`
pulled (`ollama pull nomic-embed-text && ollama pull llama3.1`).
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap

import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "graphrag-local-dev")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.1")

FILTER_LABELS = {
    "platform_type": "PlatformType",
    "cell_source": "CellSource",
    "generation_mode": "GenerationMode",
    "architecture": "Architecture",
    "perfusion_type": "PerfusionType",
    "ecm": "ECMMaterial",
}

# Explicit relationship map for each category axis.
REL_FOR_AXIS = {
    "platform_type": "HAS_PLATFORM_TYPE",
    "cell_source": "USES_CELL_SOURCE",
    "generation_mode": "HAS_GENERATION_MODE",
    "architecture": "HAS_ARCHITECTURE",
    "perfusion_type": "HAS_PERFUSION_TYPE",
    "ecm": "USES_ECM",
}

PAPER_RETURN_FIELDS = (
    "p.paper_id AS paper_id, p.doi AS doi, p.article_title AS title, "
    "p.journal_title AS journal, p.year_published AS year, p.article_url AS url"
)


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def cmd_status(driver):
    with driver.session() as session:
        rec = session.run("MATCH (m:Meta {id: 'active_project'}) RETURN m").single()
        if not rec:
            print("No project has been loaded into this Neo4j instance yet (no :Meta node found).")
            return
        m = rec["m"]
        print(f"Active project: {m['project']}")
        print(f"Papers loaded:  {m['paper_count']}")
        print(f"Loaded at:      {m['loaded_at']}")
        print(f"From CSV:       {m['csv_path']}")


def cmd_categories(driver):
    with driver.session() as session:
        for key, label in FILTER_LABELS.items():
            print(f"\n{label} (--{key.replace('_', '-')}):")
            res = session.run(f"MATCH (n:{label})<-[r]-(p:Paper) RETURN n.name AS name, count(p) AS n ORDER BY n DESC")
            for rec in res:
                print(f"  [{rec['n']:>2}] {rec['name']}")


def cmd_filter(driver, filters: dict):
    clauses = ["MATCH (p:Paper)"]
    params = {}
    for i, (axis, value) in enumerate(filters.items()):
        if not value:
            continue
        label = FILTER_LABELS[axis]
        rel = REL_FOR_AXIS[axis]
        pname = f"v{i}"
        clauses.append(f"MATCH (p)-[:{rel}]->(:{label} {{name: ${pname}}})")
        params[pname] = value

    if len(clauses) == 1:
        print("No filters given — use --platform-type / --cell-source / --generation-mode "
              "/ --architecture / --perfusion-type / --ecm")
        return

    query = "\n".join(clauses) + f"\nRETURN {PAPER_RETURN_FIELDS} ORDER BY p.year_published DESC"
    with driver.session() as session:
        res = session.run(query, **params)
        rows = list(res)
        print(f"{len(rows)} paper(s) match:\n")
        for rec in rows:
            print(f"- {rec['paper_id']} [{rec['year']}] {rec['title']}  ({rec['journal']}; DOI: {rec['doi']})")


def embed_query(text: str) -> list[float]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBEDDING_MODEL, "input": [text]},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def vector_search(driver, question: str, top_k: int, filters: dict):
    qvec = embed_query(question)

    filter_clauses = []
    params = {"qvec": qvec, "top_k": top_k}
    for i, (axis, value) in enumerate(filters.items()):
        if not value:
            continue
        label = FILTER_LABELS[axis]
        rel = REL_FOR_AXIS[axis]
        pname = f"v{i}"
        filter_clauses.append(f"MATCH (p)-[:{rel}]->(:{label} {{name: ${pname}}})")
        params[pname] = value

    pre_filter = "\n".join(filter_clauses)
    query = f"""
    CALL db.index.vector.queryNodes('evidence_embedding', $top_k_search, $qvec)
    YIELD node AS e, score
    MATCH (p:Paper)-[:HAS_EVIDENCE]->(e)
    {pre_filter}
    RETURN {PAPER_RETURN_FIELDS}, e.text AS text, score
    ORDER BY score DESC
    LIMIT $top_k
    """
    # over-fetch from the vector index before applying graph filters, since
    # the index itself doesn't know about category filters
    params["top_k_search"] = max(top_k * 8, 50)

    with driver.session() as session:
        res = session.run(query, **params)
        return list(res)


def cmd_search(driver, question, top_k, filters):
    hits = vector_search(driver, question, top_k, filters)
    if not hits:
        print("No results.")
        return
    for rec in hits:
        print(f"\n[score {rec['score']:.3f}] {rec['paper_id']} [{rec['year']}] {rec['title']}  "
              f"({rec['journal']}; DOI: {rec['doi']})")
        print(textwrap.shorten(rec["text"].replace("\n", " "), width=400, placeholder=" ..."))


def cmd_ask(driver, question, top_k, filters):
    hits = vector_search(driver, question, top_k, filters)
    if not hits:
        print("No evidence retrieved — cannot answer.")
        return

    evidence_block = "\n\n".join(
        f"[{rec['paper_id']}] {rec['title']} ({rec['year']}, {rec['journal']}, DOI: {rec['doi']})\n{rec['text']}"
        for rec in hits
    )

    system = (
        "You are a scientific writing assistant helping draft a manuscript's "
        "novelty/background section about a self-organizing, directly-reprogrammed "
        "vessel-on-a-chip platform for NAM (new approach methodology) applications. "
        "Answer ONLY using the numbered evidence excerpts provided. Cite claims "
        "inline using the bracketed paper_id, e.g. [P053]. If the evidence does not "
        "establish something, say so explicitly rather than guessing. Be precise "
        "about distinctions the user cares about: (1) direct reprogramming/transdifferentiation "
        "of somatic cells vs. iPSC differentiation vs. ETV2-style resetting of already-mature "
        "EC; (2) whether EC and SMC/mural cells were co-generated in a single protocol, "
        "separately generated and combined, or whether the model is EC-only with no SMC at all; "
        "(3) self-organized/scaffold-free tube formation vs. scaffold-guided or bioprinted "
        "architectures; (4) genuine in vitro perfusion (pump/gravity/bioreactor) vs. in vivo "
        "host-anastomosis after animal transplantation (NOT NAM-relevant) vs. both; "
        "(5) the specific ECM/matrix material(s) used for seeding."
    )
    user_msg = f"Evidence excerpts:\n\n{evidence_block}\n\nQuestion: {question}"

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"num_predict": 1200},
        },
        timeout=180,
    )
    resp.raise_for_status()
    answer_text = resp.json()["message"]["content"]
    print(answer_text)
    print("\n--- Sources ---")
    for rec in hits:
        print(f"[{rec['paper_id']}] {rec['title']} ({rec['year']}, {rec['journal']}) DOI: {rec['doi']} — {rec['url']}")


def parse_filters(args) -> dict:
    return {
        "platform_type": args.platform_type,
        "cell_source": args.cell_source,
        "generation_mode": args.generation_mode,
        "architecture": args.architecture,
        "perfusion_type": args.perfusion_type,
        "ecm": args.ecm,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("status")
    sub.add_parser("categories")

    def add_filter_args(p):
        p.add_argument("--platform-type")
        p.add_argument("--cell-source")
        p.add_argument("--generation-mode")
        p.add_argument("--architecture")
        p.add_argument("--perfusion-type")
        p.add_argument("--ecm")

    p_filter = sub.add_parser("filter")
    add_filter_args(p_filter)

    p_search = sub.add_parser("search")
    p_search.add_argument("question")
    p_search.add_argument("--top-k", type=int, default=8)
    add_filter_args(p_search)

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--top-k", type=int, default=8)
    add_filter_args(p_ask)

    args = parser.parse_args()
    driver = get_driver()

    if args.mode == "status":
        cmd_status(driver)
    elif args.mode == "categories":
        cmd_categories(driver)
    elif args.mode == "filter":
        cmd_filter(driver, parse_filters(args))
    elif args.mode in ("search", "ask"):
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
        except requests.RequestException as e:
            print(f"ERROR: cannot reach Ollama at {OLLAMA_URL} ({e}). Is `ollama serve` running?", file=sys.stderr)
            sys.exit(1)
        if args.mode == "search":
            cmd_search(driver, args.question, args.top_k, parse_filters(args))
        else:
            cmd_ask(driver, args.question, args.top_k, parse_filters(args))

    driver.close()


if __name__ == "__main__":
    main()
