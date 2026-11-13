"""
Stage 0 of the literature pipeline: query the Web of Science Expanded API
and cache raw paginated JSON results locally.

Requires your own Web of Science Expanded API key (api.clarivate.com,
typically via an institutional subscription) in WOS_API_KEY. Copy
.env.example to .env and fill in your key — .env is gitignored, so your
key never leaves your machine or gets committed.

Usage:
    python3 search_wos.py
    python3 search_wos.py --query-file my_query.txt --out-dir my_records
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

API_URL = "https://api.clarivate.com/api/wos"
PAGE_SIZE = 100


def get_api_key() -> str:
    key = os.environ.get("WOS_API_KEY")
    if not key:
        raise SystemExit(
            "WOS_API_KEY not set. Copy .env.example to .env in this directory "
            "and add your own Web of Science Expanded API key."
        )
    return key


def fetch_page(key: str, query: str, first_record: int, count: int) -> dict:
    url = API_URL + "?" + urllib.parse.urlencode(
        dict(databaseId="WOS", usrQuery=query, count=count, firstRecord=first_record)
    )
    req = urllib.request.Request(url, headers={"X-ApiKey": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-file", default=str(HERE / "search_query.txt"))
    parser.add_argument("--out-dir", default=str(HERE / "wos_records"))
    args = parser.parse_args()

    key = get_api_key()
    query = Path(args.query_file).read_text().strip()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)

    probe = fetch_page(key, query, first_record=1, count=0)
    total = probe.get("QueryResult", {}).get("RecordsFound")
    if not total:
        raise SystemExit(f"Could not determine result count from probe response: {probe}")
    print(f"Query matches {total} records. Fetching in pages of {PAGE_SIZE}...")

    for first in range(1, total + 1, PAGE_SIZE):
        dest = out_dir / f"{first:05d}.json"
        if dest.exists():
            continue
        count = min(PAGE_SIZE, total - first + 1)
        for attempt in range(6):
            try:
                data = fetch_page(key, query, first, count)
                if "Data" not in data:
                    raise ValueError(str(data)[:200])
                tmp = dest.with_suffix(".tmp")
                tmp.write_text(json.dumps(data))
                tmp.replace(dest)
                print(f"{first}: saved ({data.get('QueryResult', {})})")
                break
            except Exception as exc:
                msg = str(exc).replace(key, "[REDACTED]")[:200]
                print(f"{first}: retry {attempt} {type(exc).__name__} {msg}")
                if attempt == 5:
                    raise
                time.sleep(min(30, 2**attempt))
        time.sleep(0.6)
    print("COMPLETE")


if __name__ == "__main__":
    main()
