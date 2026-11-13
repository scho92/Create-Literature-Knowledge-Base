"""
Export the live Neo4j graph to a JSON snapshot: every node (labels +
properties, including embeddings) and every relationship, referenced by
each node's natural key (Paper.doi, category nodes' .name, Meta.id) rather
than Neo4j's internal element IDs — those aren't stable across a `--wipe`
reload, natural keys are. This is a frozen backup of the graph's current
state, separate from the CSV + classify.py/load_graph.py recipe that
reproduces it from scratch; restore it with import_graph.py.

Usage:
    python3 export_graph.py [--out data/graph_snapshot.json]
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


def node_key(labels: list[str], props: dict) -> str:
    for key_prop in _KEY_PROPS:
        if key_prop in props and props[key_prop]:
            return str(props[key_prop])
    raise ValueError(f"No natural key found for node with labels {labels}: {props}")


def jsonable(value):
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def export(driver) -> dict:
    with driver.session() as session:
        nodes = []
        for rec in session.run("MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"):
            labels, props = rec["labels"], dict(rec["props"])
            props = {k: jsonable(v) for k, v in props.items()}
            nodes.append({"labels": labels, "key": node_key(labels, props), "properties": props})

        rels = []
        for rec in session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN labels(a) AS a_labels, properties(a) AS a_props, "
            "type(r) AS rel_type, "
            "labels(b) AS b_labels, properties(b) AS b_props"
        ):
            rels.append({
                "start_labels": rec["a_labels"],
                "start_key": node_key(rec["a_labels"], rec["a_props"]),
                "type": rec["rel_type"],
                "end_labels": rec["b_labels"],
                "end_key": node_key(rec["b_labels"], rec["b_props"]),
            })

    return {"nodes": nodes, "relationships": rels}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(HERE / "data" / "graph_snapshot.json"))
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    data = export(driver)
    driver.close()

    out_path = Path(args.out)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Exported {len(data['nodes'])} nodes and {len(data['relationships'])} relationships to {out_path}")


if __name__ == "__main__":
    main()
