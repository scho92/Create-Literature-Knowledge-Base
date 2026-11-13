# Vascular-Chip Literature Knowledge Base

A literature search + Graph RAG pipeline built to support the
background/novelty section of a manuscript on self-organizing,
directly-reprogrammed vessel-on-a-chip platforms.

## Research goal

> To develop a self-organizing vessel-on-a-chip platform using directly
> reprogrammed cells.
>
> - The vessel-on-a-chip platform should spontaneously self-organize into a
>   tubular structure, minimizing the need for additional procedures to
>   create a lumen.
> - The platform should incorporate a perfusion system to support
>   physiologically relevant vascular functions.
> - The tubular structure should maintain long-term structural integrity
>   and functionality for sustained NAMs (New Approach Methodologies)
>   applications.

Every design choice below — the search terms, the screening criteria, and
the five classification axes — exists to answer one question: **has anyone
already built this, and if not, what's closest, and why doesn't it
qualify?** The knowledge base this repo produces is a writing aid for
answering that question in a manuscript, not a general-purpose literature
database.

## Why this repository exists

Manually re-reading hundreds of candidate papers every time the manuscript
needs a background citation, a novelty comparison, or a check of "has this
combination been done before" doesn't scale. This repo turns a one-time
literature search + screening pass into a queryable knowledge base: a
Neo4j graph with a local vector index that can be filtered exactly
(e.g. "self-organized AND in-vitro-perfused AND direct-reprogramming") or
searched semantically, with every answer traceable back to a DOI.

## Pipeline (two stages)

```
literature-search/  --->  (LLM-assisted screening)  --->  graphrag/
   Stage 0: search              Stage 1:                    Stage 2: classify,
   Web of Science for           feed candidate CSV           load into Neo4j,
   candidate papers              batches into an LLM          query/ask for
                                 against the criteria          manuscript drafting
                                 below, review its calls
```

1. **[`literature-search/`](../literature-search/)** — queries the Web of
   Science Expanded API and produces a raw candidate CSV. Bring your own
   API key (see that folder's README).
2. **LLM-assisted screening** — the candidate CSV was fed in batches to an
   LLM (OpenAI/Claude/Gemini were all used across different passes) with
   the inclusion/exclusion criteria below as the screening prompt; each
   batch's include/exclude/uncertain calls were then reviewed before being
   accepted. Not scripted/reproducible as code in this repo — see "Known
   limitations" below.
3. **[`graphrag/`](graphrag/)** — classifies each retained paper into five
   research-relevant axes, embeds a structured summary locally (Ollama),
   and loads everything into Neo4j for exact filtering, semantic search,
   and LLM-drafted, citation-backed answers.

## Literature search criteria

Web of Science query (Expanded API, `usrQuery` syntax — see
[`literature-search/search_query.txt`](../literature-search/search_query.txt)):

```
TS=(organoid OR chip) AND TS=(vascular OR vessel OR "direct reprogramming" OR iPSC OR "endothelial cell" OR "smooth muscle cell") AND DT=(Article) NOT DT=(Review)
```

Rationale: cast a wide net across both chip-based and organoid-based vessel
models, across every plausible EC/SMC sourcing route (iPSC differentiation,
direct reprogramming, or just "endothelial cell"/"smooth muscle cell" as a
generic catch-all), restricted to primary research articles (no reviews).
This query returned 4,545 candidate records.

## Filtering (inclusion/exclusion) criteria

The 4,545 candidates were narrowed to **60 retained papers** in stages:

1. **Journal-quality filter** — Clarivate JCR 2025, 2-year Journal Impact
   Factor > 10 (checked against the subset of hit journals registered in
   JCR), leaving 890 journal-qualifying records.
2. **Document-type / non-research screen** — excluded conference
   abstracts and other non-primary-research material, leaving 845 research
   candidates.
3. **Relevance screening** (title/abstract, then full text where
   available) against the research goal above — does the paper develop or
   characterize an endothelial/perfusable vascular organoid, tissue, or
   chip? This stage sorted the 845 into 357 included, 37 uncertain
   (resolved individually), and 451 irrelevant.
4. **Scope rules applied on top of relevance:**
   - The vascular/endothelial component's starting cell had to be a
     **human somatic cell type applicable to personalized medicine** —
     not necessarily patient-derived, but an easily-accessible somatic
     cell (e.g. fibroblasts or similar) that *could* be sourced from a
     given individual. iPSC differentiation qualifies (the iPSC itself is
     typically reprogrammed from such a somatic cell), as does true direct
     reprogramming (a non-vascular somatic cell converted straight to
     EC/SMC, bypassing pluripotency entirely) or a documented EC-to-EC
     "resetting" protocol.
   - **hESC-derived and primary/already-differentiated EC lines (e.g.
     HUVEC) were excluded** — neither starts from an accessible,
     individual-specific somatic cell, so neither fits the personalized-
     medicine framing. Likewise excluded: host-derived vascularization
     after transplantation into an animal (the vasculature isn't an
     authored EC/SMC population at all).
   - Direct reprogramming is the scope rule with the most riding on it for
     this study's novelty: it addresses personalized medicine directly
     (same accessible-somatic-cell starting material as iPSC routes) while
     skipping the pluripotent intermediate stage entirely, giving a
     substantially shorter generation timeline than iPSC differentiation.
     That combination — personalized-medicine compatibility *and* speed —
     is the significance this corpus is built to establish is still an
     open gap.
   - A paper's methods had to be independently verifiable against
     accessible abstract or full-text evidence — vague or unverifiable
     claims about cell identity or vascular structure were not enough.
5. **Final reconciliation** — duplicate/overlapping studies, source
   verification, and cell-identity re-checks across review batches
   trimmed the pool down to 60 retained papers.
6. **Post-hoc correction (2026-11-08)** — one of those 60 was excluded
   after a closer read of its primary text showed the vascular model
   relevant to this corpus's scope used HUVEC (excluded under the scope
   rule above), not iPSC-derived or direct-reprogrammed cells. It's kept
   in `literature_master.csv` (flagged `excluded_from_corpus`, with
   `exclusion_reason` explaining why) rather than deleted, so `paper_id`
   stays stable for every other paper — but it's skipped when the graph is
   built. **59 papers** are now live in
   [`graphrag/data/literature_master.csv`](graphrag/data/literature_master.csv).

*(These criteria and funnel numbers are reconstructed from this project's
own screening records; if anything here doesn't match your memory of the
actual decisions made, flag it — this file is meant to be an accurate
record for the manuscript, not just a plausible-sounding summary.)*

## Classification criteria (the five axes)

Each retained paper is classified into five axes chosen specifically
because they're what the research goal above needs to compare against:

| Axis | What it answers | Why it matters to the novelty argument |
|---|---|---|
| **Platform type** | Chip/microfluidic device vs. organoid vs. hybrid | Is it even the right category of model? |
| **Vasculature cell source + generation mode** | iPSC-derived vs. true direct reprogramming vs. mix vs. other (e.g. EC-to-EC resetting); EC+SMC co-generated, separately combined, or EC-only | Directly tests the "directly reprogrammed cells" requirement — distinguishes papers starting from an accessible human somatic cell (personalized-medicine-compatible) from hESC-/primary-EC-based work, and flags which of those also skip the iPSC intermediate for a shorter generation timeline |
| **Architecture** | Self-organized/scaffold-free vs. scaffold-guided vs. membrane-/channel-based barrier | Directly tests the "spontaneously self-organize into a tubular structure" requirement |
| **Perfusion type** | In vitro only / in vivo only / both / static | Directly tests the "incorporate a perfusion system" requirement |
| **ECM/matrix material(s)** | Multi-label (a paper can use more than one) | Documents how/whether structure is scaffolded, relevant to the "minimizing additional procedures to create a lumen" requirement |

Full design rationale and controlled vocabulary: [`graphrag/schema.md`](graphrag/schema.md).
As of this writing, **zero papers** in the 59-paper retained corpus satisfy true
direct reprogramming + self-organized architecture + in-vitro perfusion
simultaneously — that gap is itself a key data point for the manuscript's
novelty argument (see `graphrag/README.md`'s `query_rag.py filter` example).

## Repository layout

This is one of possibly several research projects in this repo — see
[`../PROJECTS.md`](../PROJECTS.md) at the repo root for the full registry
and how multiple projects' knowledge bases coexist (Neo4j only runs one
active database at a time).

```
fro/
├── PROJECTS.md               registry of all research projects in this repo
├── literature-search/        Stage 0 — Web of Science search (shared across projects, bring your own API key)
└── vascularized-NAMs/        this project
    ├── README.md              (this file)
    └── graphrag/              Stage 1 — classification, Neo4j graph, RAG query/ask
        ├── data/literature_master.csv   the final 59-paper corpus
        ├── schema.md                    graph design + classification rationale
        └── classify.py / load_graph.py / query_rag.py
```

See each folder's own README for setup and usage.

## Known limitations

- Classification for most papers (54/59) reflects manual review against
  primary sources, not the keyword heuristic alone — see
  `graphrag/README.md`'s "Known data caveats" for the confidence-tier
  breakdown (`user-confirmed` vs. `provisional`).
- The screening/filtering decisions (batch-by-batch include/exclude calls
  made by feeding candidate-CSV batches to an LLM against the criteria
  above, then reviewing its output) were not scripted and are not
  reproducible by running code in this repo — only the search step and the
  classification/graph-loading step are.
