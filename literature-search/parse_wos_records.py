"""
Stage 0b of the literature pipeline: parse raw Web of Science Expanded API
JSON (from search_wos.py) into a flat CSV of candidate papers, ready for
manual/LLM screening ahead of the graphrag/ classification + load step.

Usage:
    python3 parse_wos_records.py
    python3 parse_wos_records.py --records-dir my_records --out my_candidates.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

HERE = Path(__file__).parent


def arr(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def texts(x):
    if isinstance(x, str):
        return [x]
    if isinstance(x, (int, float)):
        return []
    if isinstance(x, list):
        return sum([texts(y) for y in x], [])
    if isinstance(x, dict):
        if "content" in x:
            return texts(x["content"])
        return sum([texts(v) for k, v in x.items() if k in ("abstract_text", "p", "abstract")], [])
    return []


def parse_record(r: dict) -> dict:
    st = r["static_data"]
    s = st["summary"]
    titles = {x["type"]: x.get("content", "") for x in arr(s.get("titles", {}).get("title"))}
    ids = arr(r.get("dynamic_data", {}).get("cluster_related", {}).get("identifiers", {}).get("identifier"))
    pub = s.get("publishers", {}).get("publisher", {})
    doi = next((x.get("value") for x in ids if x.get("type") == "doi"), "")
    return {
        "Web of Science ID": r["UID"],
        "year published": s.get("pub_info", {}).get("pubyear", ""),
        "article title": titles.get("item", ""),
        "journal title": titles.get("source", ""),
        "authors name": "; ".join(x.get("full_name", "") for x in arr(s.get("names", {}).get("name"))),
        "publisher": "; ".join(x.get("full_name", "") for z in arr(pub) for x in arr(z.get("names", {}).get("name"))),
        "DOI": doi,
        "article URL": f"https://doi.org/{doi}" if doi else "",
        "document_types": "; ".join(arr(s.get("doctypes", {}).get("doctype"))),
        "abstract": "\n".join(texts(st.get("fullrecord_metadata", {}).get("abstracts", {}))),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records-dir", default=str(HERE / "wos_records"))
    parser.add_argument("--out", default=str(HERE / "candidates.csv"))
    args = parser.parse_args()

    rows = []
    seen = set()
    for p in sorted(Path(args.records_dir).glob("*.json")):
        data = json.loads(p.read_text())
        for r in arr(data["Data"]["Records"]["records"]["REC"]):
            row = parse_record(r)
            if row["Web of Science ID"] in seen:
                continue
            seen.add(row["Web of Science ID"])
            rows.append(row)

    if not rows:
        raise SystemExit(f"No records found in {args.records_dir} — run search_wos.py first.")

    fieldnames = list(rows[0].keys())
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} unique candidate papers to {args.out}")


if __name__ == "__main__":
    main()
