"""
ETL: literature_master.csv -> Neo4j graph + vector index (lean v2 schema).

Scope is intentionally narrow per the research use-case: only five axes are
classified and stored (platform type, vasculature cell source, generation
mode, self-organization architecture, perfusion type, ECM/matrix) plus a
compact paper-identity block (paper_id, doi, title, journal, year, URL).
Screening/review-process metadata (JIF, source lookup status, full-text
availability, exclusion notes, etc.) and the original batch-report
paragraphs are deliberately NOT ingested — see schema.md for rationale.

Usage:
    python3 load_graph.py [--wipe] [--limit N]

Embeddings run entirely locally via Ollama (no API key / cost) — see
OLLAMA_URL / OLLAMA_EMBED_MODEL below. Requires `ollama serve` running and
the embed model pulled: `ollama pull nomic-embed-text`.

Env vars (loaded from graphrag/.env if present):
    OLLAMA_URL (default http://localhost:11434)
    OLLAMA_EMBED_MODEL (default nomic-embed-text)
    NEO4J_URI (default bolt://localhost:7687)
    NEO4J_USER (default neo4j)
    NEO4J_PASSWORD (default graphrag-local-dev)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import requests
from dotenv import load_dotenv
from neo4j import GraphDatabase

import classify

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

GRAPHRAG_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(GRAPHRAG_DIR, "data", "literature_master.csv")

# Derived from the parent folder name (e.g. ".../vascularized-NAMs/graphrag"
# -> "vascularized-NAMs") so copying this whole graphrag/ folder as a
# template for a new, unrelated research project needs no code edit here —
# see ../../PROJECTS.md for the registry this name is checked against.
PROJECT_NAME = os.path.basename(os.path.dirname(GRAPHRAG_DIR))

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "graphrag-local-dev")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBEDDING_DIM = 768


def clean_doi(raw: str) -> str:
    doi = (raw or "").strip().rstrip(".,;)")
    return doi.lower()


def load_csv_rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for i, row in enumerate(reader, start=2):  # row 1 is header, data starts at row 2
            row["_row_id"] = i
            rows.append(row)
        return rows


def truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def apply_axis_overrides(
    row: dict, platform_type: str, architecture: str, perfusion_type: str, ecm_materials: list[str]
):
    """Manual per-paper corrections (platform type/architecture/perfusion/ECM)
    live in the `*_override` CSV columns, populated from a human reviewer's
    paper-by-paper read-through (see data/literature_master.csv
    `axis_review_confidence` / `axis_review_note`). When an override column
    is non-empty it wins over the keyword-heuristic classify.* output;
    otherwise the heuristic result is kept unchanged. This lets a large batch
    of reviewer corrections be layered in without hand-editing the raw
    free-text columns to coincidentally retrigger the right heuristic bucket.
    """
    platform_override = (row.get("platform_type_override") or "").strip()
    arch_override = (row.get("architecture_override") or "").strip()
    perf_override = (row.get("perfusion_type_override") or "").strip()
    ecm_override = (row.get("ecm_materials_override") or "").strip()

    if platform_override:
        platform_type = platform_override
    if arch_override:
        architecture = arch_override
    if perf_override:
        perfusion_type = perf_override
    if ecm_override:
        ecm_materials = [e.strip() for e in ecm_override.split(";") if e.strip()]

    return platform_type, architecture, perfusion_type, ecm_materials


def build_evidence_text(payload: dict) -> str:
    """Compact, structured summary built ONLY from the five research-relevant
    axes + short raw snippets. This is what gets embedded, so it stays small
    and strictly on-topic (no reviewer/process narrative)."""
    lines = [
        f"Paper {payload['paper_id']} ({payload['year_published']}): {payload['article_title']}",
        f"Platform: {payload['platform_type']}"
        + (f" (raw: {truncate(payload['culture_dish_or_chip_raw'], 160)})" if payload["culture_dish_or_chip_raw"] else ""),
        f"Vasculature cell source: {payload['cell_source']} | Generation mode: {payload['generation_mode']}"
        + (f" | Reprogramming factor: {payload['reprogramming_factor_raw']}" if payload["reprogramming_factor_raw"] else ""),
    ]
    if payload["ec_source_assessment_raw"]:
        lines.append(f"  Cell-source evidence: {truncate(payload['ec_source_assessment_raw'], 300)}")
    lines.append(f"Architecture: {payload['architecture']}")
    lines.append(f"Perfusion: {payload['perfusion_type']}")
    if payload["vascular_architecture_assessment_raw"]:
        lines.append(f"  Architecture/perfusion evidence: {truncate(payload['vascular_architecture_assessment_raw'], 300)}")
    lines.append(f"ECM/matrix: {', '.join(payload['ecm_materials'])}"
                 + (f" (raw: {truncate(payload['matrix_raw'], 160)})" if payload["matrix_raw"] else ""))
    if payload.get("axis_review_note"):
        conf = payload.get("axis_review_confidence") or "unconfirmed"
        lines.append(f"  Reviewer note ({conf}): {truncate(payload['axis_review_note'], 300)}")
    return "\n".join(lines)


def embed_texts(texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBEDDING_MODEL, "input": batch},
            timeout=120,
        )
        resp.raise_for_status()
        out.extend(resp.json()["embeddings"])
    return out


def ensure_constraints(tx):
    tx.run("CREATE CONSTRAINT paper_doi IF NOT EXISTS FOR (p:Paper) REQUIRE p.doi IS UNIQUE")
    tx.run("CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE")
    tx.run("CREATE CONSTRAINT platformtype_name IF NOT EXISTS FOR (n:PlatformType) REQUIRE n.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT cellsource_name IF NOT EXISTS FOR (n:CellSource) REQUIRE n.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT genmode_name IF NOT EXISTS FOR (n:GenerationMode) REQUIRE n.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT arch_name IF NOT EXISTS FOR (n:Architecture) REQUIRE n.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT perfusion_name IF NOT EXISTS FOR (n:PerfusionType) REQUIRE n.name IS UNIQUE")
    tx.run("CREATE CONSTRAINT ecm_name IF NOT EXISTS FOR (n:ECMMaterial) REQUIRE n.name IS UNIQUE")
    tx.run(
        """
        CREATE VECTOR INDEX evidence_embedding IF NOT EXISTS
        FOR (e:EvidenceChunk) ON (e.embedding)
        OPTIONS { indexConfig: {
          `vector.dimensions`: $dim,
          `vector.similarity_function`: 'cosine'
        }}
        """,
        dim=EMBEDDING_DIM,
    )


def wipe_graph(tx):
    tx.run("MATCH (n) DETACH DELETE n")


MERGE_PAPER_CYPHER = """
MERGE (p:Paper {doi: $doi})
SET p.paper_id = $paper_id,
    p.article_title = $article_title,
    p.journal_title = $journal_title,
    p.year_published = $year_published,
    p.article_url = $article_url,
    p.cell_type_raw = $cell_type_raw,
    p.reprogramming_factor_raw = $reprogramming_factor_raw,
    p.matrix_raw = $matrix_raw,
    p.culture_dish_or_chip_raw = $culture_dish_or_chip_raw,
    p.model_category_raw = $model_category_raw,
    p.ec_source_assessment_raw = $ec_source_assessment_raw,
    p.vascular_architecture_assessment_raw = $vascular_architecture_assessment_raw,
    p.axis_review_confidence = $axis_review_confidence,
    p.axis_review_note = $axis_review_note

MERGE (pt:PlatformType {name: $platform_type})
MERGE (p)-[:HAS_PLATFORM_TYPE]->(pt)

MERGE (cs:CellSource {name: $cell_source})
MERGE (p)-[:USES_CELL_SOURCE]->(cs)

MERGE (gm:GenerationMode {name: $generation_mode})
MERGE (p)-[:HAS_GENERATION_MODE]->(gm)

MERGE (a:Architecture {name: $architecture})
MERGE (p)-[:HAS_ARCHITECTURE]->(a)

MERGE (fs:PerfusionType {name: $perfusion_type})
MERGE (p)-[:HAS_PERFUSION_TYPE]->(fs)

WITH p
UNWIND $ecm_materials AS ecm_name
MERGE (ecm:ECMMaterial {name: ecm_name})
MERGE (p)-[:USES_ECM]->(ecm)

WITH p
MERGE (e:EvidenceChunk {doi: $doi})
SET e.paper_id = $paper_id,
    e.text = $evidence_text,
    e.embedding = $embedding
MERGE (p)-[:HAS_EVIDENCE]->(e)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wipe", action="store_true", help="delete all nodes/relationships before loading")
    parser.add_argument("--limit", type=int, default=None, help="only load first N rows (debug)")
    args = parser.parse_args()

    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR: cannot reach Ollama at {OLLAMA_URL} ({e}). Is `ollama serve` running?", file=sys.stderr)
        sys.exit(1)

    print("Loading CSV rows...")
    rows = load_csv_rows(CSV_PATH)
    excluded = [r for r in rows if (r.get("excluded_from_corpus") or "").strip().upper() == "TRUE"]
    rows = [r for r in rows if (r.get("excluded_from_corpus") or "").strip().upper() != "TRUE"]
    if excluded:
        print(f"  Skipping {len(excluded)} excluded row(s): "
              f"{', '.join('P%03d' % r['_row_id'] for r in excluded)}")
    if args.limit:
        rows = rows[: args.limit]
    print(f"  {len(rows)} rows")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        if args.wipe:
            print("Wiping existing graph...")
            session.execute_write(wipe_graph)
        print("Ensuring constraints + vector index...")
        session.execute_write(ensure_constraints)

    payloads = []
    for row in rows:
        doi = clean_doi(row.get("DOI", ""))
        row_id = row["_row_id"]
        if not doi:
            doi = f"row:{row_id}"
        paper_id = f"P{row_id:03d}"

        cell_type_raw = row.get("cell type", "").strip()
        reprogramming_factor_raw = row.get("reprogramming factor", "").strip()
        matrix_raw = row.get("matrix", "").strip()
        culture_dish_or_chip_raw = row.get("culture dish or chip", "").strip()
        model_category_raw = row.get("model category", "").strip()
        ec_source_assessment_raw = row.get("EC source assessment", "").strip()
        vascular_architecture_assessment_raw = row.get("vascular architecture assessment", "").strip()
        screening_notes = row.get("screening notes", "").strip()
        methods = row.get("methods", "").strip()

        article_title = row.get("article title", "").strip()

        platform_type = classify.classify_platform_type(culture_dish_or_chip_raw, methods, article_title)
        cell_source = classify.classify_cell_source(ec_source_assessment_raw, cell_type_raw, reprogramming_factor_raw)
        generation_mode = classify.classify_generation_mode(
            ec_source_assessment_raw, cell_type_raw, screening_notes, article_title
        )
        architecture = classify.classify_architecture(vascular_architecture_assessment_raw, screening_notes)
        perfusion_type = classify.classify_perfusion_type(vascular_architecture_assessment_raw, screening_notes)
        ecm_materials = classify.classify_ecm_materials(matrix_raw)

        platform_type, architecture, perfusion_type, ecm_materials = apply_axis_overrides(
            row, platform_type, architecture, perfusion_type, ecm_materials
        )
        axis_review_confidence = (row.get("axis_review_confidence") or "").strip()
        axis_review_note = (row.get("axis_review_note") or "").strip()

        payload = dict(
            doi=doi,
            paper_id=paper_id,
            article_title=row.get("article title", "").strip(),
            journal_title=row.get("journal title", "").strip(),
            year_published=row.get("year published", "").strip(),
            article_url=row.get("article URL", "").strip(),
            cell_type_raw=cell_type_raw,
            reprogramming_factor_raw=reprogramming_factor_raw,
            matrix_raw=matrix_raw,
            culture_dish_or_chip_raw=culture_dish_or_chip_raw,
            model_category_raw=model_category_raw,
            ec_source_assessment_raw=ec_source_assessment_raw,
            vascular_architecture_assessment_raw=vascular_architecture_assessment_raw,
            platform_type=platform_type,
            cell_source=cell_source,
            generation_mode=generation_mode,
            architecture=architecture,
            perfusion_type=perfusion_type,
            ecm_materials=ecm_materials,
            axis_review_confidence=axis_review_confidence,
            axis_review_note=axis_review_note,
        )
        payload["evidence_text"] = build_evidence_text(payload)
        payloads.append(payload)

    evidence_texts = [p["evidence_text"] for p in payloads]
    print(f"Requesting {len(evidence_texts)} embeddings from Ollama ({EMBEDDING_MODEL})...")
    embeddings = embed_texts(evidence_texts)
    for payload, emb in zip(payloads, embeddings):
        payload["embedding"] = emb

    print("Loading into Neo4j...")
    with driver.session() as session:
        for i, payload in enumerate(payloads, start=1):
            session.execute_write(lambda tx, p=payload: tx.run(MERGE_PAPER_CYPHER, **p))
            if i % 10 == 0 or i == len(payloads):
                print(f"  {i}/{len(payloads)} papers loaded")

        # Singleton marker recording which project is currently loaded into
        # this shared Neo4j instance (Community Edition only supports one
        # active database) — lets a caller check what's live via
        # `query_rag.py status` instead of reloading unnecessarily, or
        # inspecting paper content to guess.
        session.run(
            "MERGE (m:Meta {id: 'active_project'}) "
            "SET m.project = $project, m.paper_count = $paper_count, "
            "m.loaded_at = datetime(), m.csv_path = $csv_path",
            project=PROJECT_NAME,
            paper_count=len(payloads),
            csv_path=CSV_PATH,
        )

    driver.close()
    print(f"Done. Active project in Neo4j is now '{PROJECT_NAME}' ({len(payloads)} papers).")


if __name__ == "__main__":
    main()
