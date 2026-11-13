# Vascular-chip literature Graph RAG

A Neo4j-backed graph + vector index over `data/literature_master.csv`
(59 retained papers — the CSV has 60 rows, but 1 is flagged
`excluded_from_corpus` and skipped at load time; see "Known data caveats"
below), built as a writing aid for the manuscript's
novelty/background section. Scope is deliberately lean: only five
research-relevant axes are stored and embedded — see `schema.md` for the
full design and rationale.

1. **Platform type** — chip assay vs. organoid
2. **Vasculature cell source** — iPSC-derived vs. true direct reprogramming
   (non-vascular somatic cell -> EC/SMC, bypassing pluripotency entirely —
   currently zero papers in this corpus qualify) vs. mix (EC and non-EC/
   mural cells sourced differently) vs. other (ETV2-style EC-to-EC
   "resetting" of an already-mature EC, e.g. the Rafii-lab R-VEC work —
   not iPSC-derived and not a genuine lineage conversion) vs. unresolved,
   **and** whether EC+SMC were co-generated in one protocol, separately
   generated and combined, or EC-only (no SMC at all)
3. **Architecture** — self-organized/scaffold-free vs. scaffold-guided
   (kept as a 5th axis alongside the four below — still central to the
   novelty argument)
4. **Perfusion type** — in vitro / in vivo / both / static
5. **ECM/matrix material(s)** used for seeding — multi-label (a paper can
   use more than one)

Screening/review-process metadata (JIF, source-lookup status, full-text
availability, exclusion commentary, etc.) and the original batch-report
paragraphs are intentionally **not** ingested — they don't answer the
research questions this tool exists to support, and leaving them out keeps
storage and embedding cost down.

## Paper identity -> vector space link

Every `Paper` node has a compact identity block: `paper_id` (a short key
like `P009`, zero-padded from the CSV row number), `doi`, `article_title`,
`journal_title`, `year_published`, `article_url`. Every embedded
`EvidenceChunk` carries `paper_id`/`doi` directly, so any vector search hit
traces straight back to full citation info without extra joins.

## 1. One-time setup

Embeddings and the `ask` generation step both run **entirely locally via
Ollama** — no OpenAI/Anthropic API key or cost required.

```bash
cd graphrag
pip3 install -r requirements.txt
docker compose up -d        # starts Neo4j 5.26 on bolt://localhost:7687

# Ollama (https://ollama.com) must be installed and running (`ollama serve`):
ollama pull nomic-embed-text   # local embedding model (768-dim, ~274MB)
ollama pull llama3.1           # local chat model, used only by `ask`
```

No `.env` is required for the local setup above. If you'd rather use the
Aura/cloud Neo4j instance instead of local Docker, copy `.env.example` to
`.env` and set `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` (and
`NEO4J_DATABASE` if your Aura instance's default database isn't `neo4j`).
`OLLAMA_URL`, `OLLAMA_EMBED_MODEL`, and `OLLAMA_CHAT_MODEL` are also
overridable via `.env` if you run Ollama elsewhere or prefer a different
local model.

Browser UI (optional, to poke around the graph visually): http://localhost:7474
— login `neo4j` / `graphrag-local-dev` (or whatever you set in
`docker-compose.yml` / `.env`).

## 2. Load the graph

```bash
python3 load_graph.py --wipe
```

Parses all 60 CSV rows, classifies each into the five axes above
(`classify.py` — transparent keyword rules, raw text always kept on the
`Paper` node for audit), builds a compact structured summary per paper,
embeds it locally via Ollama (`nomic-embed-text`), and loads everything into
Neo4j with a vector index (`evidence_embedding`).

Use `--limit N` for a fast smoke-test load of the first N rows before
committing to the full run. Re-running is safe (idempotent `MERGE`s); use
`--wipe` to start clean.

## 3. Query it

```bash
# What category values exist in each axis, and how many papers in each?
python3 query_rag.py categories

# Exact graph filter (no LLM call) — e.g. the core novelty intersection:
python3 query_rag.py filter \
  --cell-source "Direct reprogramming (non-vascular somatic cell -> EC/SMC, bypasses pluripotency)" \
  --generation-mode "EC and SMC co-generated in one protocol" \
  --architecture "Self-organized / self-assembled (no scaffold)" \
  --perfusion-type "In vitro only"
# ^ As of 2026-11-06 this returns 0 papers — no paper in this 59-paper corpus
# uses TRUE direct reprogramming (vs. iPSC differentiation or EC-to-EC
# resetting) for a self-organized, in-vitro-perfused vascular model. That
# gap is itself a key data point for the manuscript's novelty argument.

# Which papers use a given ECM?
python3 query_rag.py filter --ecm "Fibrin"

# Semantic search over evidence summaries, optionally pre-filtered:
python3 query_rag.py search "longest in vitro vessel perfusion duration" --top-k 5

# Full hybrid RAG: retrieve + ask a local LLM (Ollama/llama3.1) to draft a cited paragraph:
python3 query_rag.py ask "What is the longest reported in vitro (non-animal) \
perfusion duration for self-assembled vascular tubes, and which papers \
report it?"
```

`ask` answers strictly from the retrieved evidence summaries and cites them
by `paper_id` (e.g. `[P053]`), followed by a Sources list with full
journal/title/year/DOI/URL — ready to pull straight into the manuscript
draft and swap for real citations.

Filter flags: `--platform-type`, `--cell-source`, `--generation-mode`,
`--architecture`, `--perfusion-type`, `--ecm`. Run `categories` first to see
the exact controlled-vocabulary strings each one accepts.

## Known data caveats (carried over from the CSV)

- Rows 62, 66, 74 are provisional retentions based on secondary-source
  evidence.
- Row 12 may not have an authored EC/vascular component (host-mouse-derived
  vascularization post-transplant) — not specially flagged in this lean
  schema; check `data/literature_master.csv` row 12 directly if needed.
- Row 18's cited article URL may be mismatched — not re-verified.
- Classification into the five axes is rule-based (`classify.py`); the raw
  free-text CSV fields are kept on each `Paper` node (`*_raw` properties) so
  you can check why a classification was made and correct the keyword rules
  if a paper is miscategorized.
- Architecture, PerfusionType, and ECM for 54/59 papers reflect a manual
  reviewer pass against the primary literature (DOI-verified), not the
  keyword heuristic — see `schema.md`'s "Manual axis-review overrides"
  section. 34 are `user-confirmed` (primary source read directly), 20 are
  `provisional` (best read from available evidence, not yet independently
  verified against full text); both tiers are live in the graph, tagged on
  `Paper.axis_review_confidence` / `.axis_review_note` and visible in
  `ask`/`search` output so provisional calls can be flagged in the
  manuscript if needed.
- One row (`excluded_from_corpus = TRUE`) is kept in the CSV for audit
  trail but skipped by `load_graph.py` — see `schema.md`'s "Manual
  axis-review overrides" section. Rows are never physically deleted for
  this: `paper_id` is derived from CSV row position
  (`enumerate(reader, start=2)`), so deleting a row would silently
  renumber every subsequent paper.
