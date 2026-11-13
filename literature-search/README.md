# Literature search (Stage 0)

This is the first stage of the pipeline, run **before** a project's own
`graphrag/` (see [`../PROJECTS.md`](../PROJECTS.md) for the registry of
projects in this repo — each has its own `graphrag/`, but this search tool
is shared/topic-agnostic across all of them). It searches Web of Science
for candidate papers and produces a flat CSV you then screen/curate into
the shape that project's `graphrag/data/literature_master.csv` expects.
Nothing here requires or stores anyone's API key — you bring your own.

## What this reproduces

The [`vascularized-NAMs`](../vascularized-NAMs/) project's literature
review used this exact Web of Science query (see `search_query.txt`):

```
TS=(organoid OR chip) AND TS=(vascular OR vessel OR "direct reprogramming" OR iPSC OR "endothelial cell" OR "smooth muscle cell") AND DT=(Article) NOT DT=(Review)
```

against the **Web of Science Expanded API** (`api.clarivate.com/api/wos`),
which returned 4,545 candidate records. From there, that project
manually/LLM-screened titles/abstracts in batches, verified methods against
full text, checked Journal Impact Factor thresholds, and classified the
retained ~60 papers into the 5 research axes documented in
`../vascularized-NAMs/graphrag/schema.md`. That screening/classification
judgment call is not automated by this stage — it's inherently manual
review. This stage only automates the reproducible, key-gated part:
getting candidate records out of Web of Science.

To run your own literature search — for a brand new project, or to extend
an existing one with newly published papers — replace the query in
`search_query.txt` with your own research question (Web of Science's
`usrQuery` syntax: `TS=` topic, `DT=` document type, etc.).

## 1. Get a Web of Science API key

You need a **Web of Science Expanded API** key from Clarivate
(https://developer.clarivate.com/apis/wos), typically available through an
institutional/library subscription. This is a different product from the
free "Starter API" — the Expanded API supports the full `usrQuery` syntax
used here (`TS=`, `DT=`, boolean operators, etc.).

Each user brings their own key. It is never stored in this repo.

## 2. Setup

```bash
cd literature-search
pip3 install -r requirements.txt
cp .env.example .env
# edit .env and set WOS_API_KEY=<your own key>
```

`.env` is gitignored — your key stays local.

## 3. Search

```bash
python3 search_wos.py
```

This pages through the Expanded API (100 records/page, with retry/backoff)
and caches each page as raw JSON under `wos_records/` (also gitignored —
Clarivate's terms of use restrict bulk redistribution of downloaded
records, so don't commit this directory). Re-running is safe/resumable:
it skips any page already cached on disk.

Use `--query-file` / `--out-dir` to point at a different query or output
location.

## 4. Parse into a candidate CSV

```bash
python3 parse_wos_records.py
```

Flattens the cached JSON into `candidates.csv` (also gitignored) with one
row per unique paper: `Web of Science ID`, `year published`,
`article title`, `journal title`, `authors name`, `publisher`, `DOI`,
`article URL`, `document_types`, `abstract`.

## 5. Next step: screening and classification

`candidates.csv` is a raw search result, not a finished literature
database — it still needs title/abstract screening against your inclusion
criteria, full-text verification, and classification into whichever
project's `graphrag/` you're feeding. Once you have a curated CSV shaped
like that project's `data/literature_master.csv` columns, drop it in there
and continue with that project's own `graphrag/README.md`
(`python3 load_graph.py --wipe`) — e.g.
[`../vascularized-NAMs/graphrag/`](../vascularized-NAMs/graphrag/) for the
existing project, or a newly created project's `graphrag/` (see
[`../PROJECTS.md`](../PROJECTS.md) for how to start one).
