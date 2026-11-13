# Research projects registry

Each project below has its own `graphrag/` folder (classification schema,
Neo4j loader, query tool, and `data/literature_master.csv`), independent
of every other project. `literature-search/` (Web of Science search) is
shared/reusable across all of them — it's just a generic search tool, not
tied to any one research topic.

**Neo4j is a single local instance (Community Edition — one active
database at a time)**, so only one project's data can be loaded and
queryable at once. Run `python3 <project>/graphrag/load_graph.py --wipe`
to make a project active; check what's currently active with
`python3 <any-project>/graphrag/query_rag.py status`.

When asked a question, identify the relevant project from the topic
descriptions below, confirm (via `status`) whether it's already loaded,
and only reload if switching to a different project than what's active.

| Project folder | Topic | Status |
|---|---|---|
| [`vascularized-NAMs/`](vascularized-NAMs/) | Self-organizing, directly-reprogrammed vessel-on-a-chip platforms for New Approach Methodologies (NAMs) — see `vascularized-NAMs/README.md` for the full research goal and inclusion criteria. | Active corpus: 59 papers |

## Starting a new project

`graphrag/`'s *infrastructure* (Neo4j + Ollama + the override-CSV
correction workflow) is reusable; its *classification schema*
(`classify.py`'s specific axes and keyword markers) is NOT — it was
built for vascular-chip biology specifically. A genuinely different
research topic (e.g. a different field entirely) needs its own
classification axes designed from scratch, not just a new CSV plugged
into the existing `classify.py`.

To start one:
1. `mkdir <new-project-name>` at this repo's root.
2. Copy `literature-search/` reuse is automatic (it's shared, topic-agnostic — just point `search_query.txt` at the new topic).
3. Copy `vascularized-NAMs/graphrag/` as a *template* into
   `<new-project-name>/graphrag/`, then redesign `classify.py`'s axes,
   `schema.md`, and the README for the new topic before loading any data.
4. Add a row to the table above.
