"""
Restore a JSON snapshot produced by export_graph.py back into Neo4j.
Nodes are MERGEd by label + natural key (doi/name/id), so this is safe to
re-run; relationships are MERGEd by (start key, type, end key). This does
NOT replace classify.py/load_graph.py as the primary way to build the
graph from the CSV — it's for restoring a frozen snapshot verbatim (e.g.
after a `--wipe`, or on a different machine) without re-running
classification or re-requesting embeddings from Ollama.

Usage:
    python3 import_graph.py [--snapshot data/graph_snapshot.json] [--wipe]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "graphrag-local-dev")

_KEY_PROPS = ("doi", "name", "id")


def key_prop_for(labels: list[str]) -> str:
    # Mirrors export_graph.py's node_key() priority, but returns the
    # property NAME (not its value) so the Cypher MERGE can reference it.
    return _KEY_PROPS[0] if "Paper" in labels or "EvidenceChunk" in labels else (
        _KEY_PROPS[2] if "Meta" in labels else _KEY_PROPS[1]
    )


def wipe(tx):
    tx.run("MATCH (n) DETACH DELETE n")


def import_snapshot(driver, data: dict) -> None:
    with driver.session() as session:
        for node in data["nodes"]:
            labels = node["labels"]
            key_prop = key_prop_for(labels)
            label_str = ":".join(labels)
            session.run(
                f"MERGE (n:{label_str} {{{key_prop}: $key}}) SET n += $props",
                key=node["key"], props=node["properties"],
            )

        for rel in data["relationships"]:
            a_key_prop = key_prop_for(rel["start_labels"])
            b_key_prop = key_prop_for(rel["end_labels"])
            a_label_str = ":".join(rel["start_labels"])
            b_label_str = ":".join(rel["end_labels"])
            session.run(
                f"MATCH (a:{a_label_str} {{{a_key_prop}: $a_key}}), "
                f"(b:{b_label_str} {{{b_key_prop}: $b_key}}) "
                f"MERGE (a)-[r:{rel['type']}]->(b)",
                a_key=rel["start_key"], b_key=rel["end_key"],
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", default=str(HERE / "data" / "graph_snapshot.json"))
    parser.add_argument("--wipe", action="store_true", help="Delete all existing graph data first")
    args = parser.parse_args()

    data = json.loads(Path(args.snapshot).read_text())

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    if args.wipe:
        with driver.session() as session:
            session.execute_write(wipe)
        print("Wiped existing graph.")

    import_snapshot(driver, data)
    driver.close()
    print(f"Imported {len(data['nodes'])} nodes and {len(data['relationships'])} relationships from {args.snapshot}")


if __name__ == "__main__":
    main()
