# Graph RAG schema — vascular-chip literature graph (v2, lean)

Purpose: a Neo4j property graph + vector index over `literature_master.csv`
(59 retained papers — the CSV has 60 rows, 1 flagged `excluded_from_corpus`
and skipped at load time), used as a writing aid for the manuscript's
novelty/background section. Scope is deliberately restricted to content
the user identified as research-relevant — this is not a general-purpose
literature database, and screening/review-process metadata (JIF, source
lookup status, methods review status, full-text availability, screening
notes about exclusions, etc.) is intentionally excluded from the graph to
keep storage and embeddings lean.

## Design principle: Paper identity -> vector space link

Every `Paper` node carries a compact identity block (`paper_id`, `doi`,
`article_title`, `journal_title`, `year_published`, `article_url`). This is
the only "citation metadata" stored. Every `EvidenceChunk` (the embedded,
vector-searchable node) is linked back to its `Paper` via `HAS_EVIDENCE` and
also carries `paper_id`/`doi` directly, so a vector search hit can always be
traced straight back to journal/title/year/URL without extra joins.

`paper_id` is a short synthetic key (`P009`, `P010`, ... zero-padded from the
original CSV row number) — easier to cite in conversation/drafts than a raw
DOI string, while `doi` remains the canonical unique identifier.

## Node types

### `Paper` (key = `doi`; also unique on `paper_id`)
```
paper_id, doi, article_title, journal_title, year_published, article_url
```
Plus a small set of *raw supporting fields* — kept mostly because they are
direct inputs to the five classifiers below, for audit/traceability:
```
cell_type_raw, reprogramming_factor_raw, matrix_raw,
culture_dish_or_chip_raw, model_category_raw,
ec_source_assessment_raw, vascular_architecture_assessment_raw
```
No JIF, no screening/review-status fields, no full batch-report text is
stored on `Paper` — that content does not answer the research questions this
RAG exists to support.

`model_category_raw` is the one exception to "direct classifier input": as
of 2026-11-07 it is stored for audit only and is **not** read by
`classify_platform_type` — it's a coarse, 5-bucket screening-stage label
(identical strings shared across many papers), not paper-specific evidence;
see "Fixed 2026-11-07" below.

### `PlatformType` (axis 1 — chip assay or organoid)
- `Chip / microfluidic device`
- `Organoid (no chip/device)`
- `Organoid-on-chip / hybrid`
- `Unresolved / not reported`

### `CellSource` (axis 2a — vasculature cell source)
5-bucket scheme, revised twice on 2026-11-06 (see revision history in
`classify.py`'s inline comments for the full back-and-forth):
- `iPSC-derived` — the EC population is iPSC-derived (hESC-only papers, with
  no iPSC mention at all, do NOT get this bucket — see below)
- `Direct reprogramming (non-vascular somatic cell -> EC/SMC, bypasses
  pluripotency)` — TRUE transdifferentiation only: a non-vascular,
  non-pluripotent somatic cell (e.g. fibroblast) is converted directly into
  an EC/SMC, never passing through a pluripotent-stem-cell intermediate.
  **Currently zero papers in this 59-paper corpus fall in this bucket** —
  every candidate found by keyword search turned out to be either (a)
  ETV2-assisted iPSC/hPSC differentiation (still passes through a
  pluripotent intermediate — P009, P010, P011, P012, P034) or (b) EC-to-EC
  resetting of an already-mature EC (P054, see `Other` below), not a
  genuine lineage conversion from a non-vascular cell.
- `Mix (EC and non-EC/mural cells sourced differently)` — within one paper,
  the EC population and the non-EC/mural population (SMC/pericyte/
  macrophage) are sourced by different methods (e.g. EC is iPSC-derived but
  the pericytes/SMC are primary cells).
- `Other (e.g. ETV2-mediated resetting of an already-mature EC; EC-to-EC,
  not iPSC-derived, not a lineage conversion from a non-vascular cell)` —
  currently just the Rafii-lab R-VEC paper (P054): ETV2 transcriptionally
  "resets" an already-differentiated, mature EC (HUVEC / adult-tissue EC)
  into a more plastic EC state. This was briefly merged into `Direct
  reprogramming` per an initial user instruction, then explicitly split
  back out into its own bucket after the user re-reviewed the paper and
  confirmed it is NOT true direct reprogramming (it never leaves the EC
  lineage, so it doesn't belong with genuine non-vascular-cell -> EC
  conversion, but it's also clearly not iPSC-derived) — hence its own
  `Other` bucket rather than forcing it into either neighboring bucket.
- `Unresolved / not reported` — includes papers using ONLY hESC (no iPSC
  mention at all); hESC has no dedicated bucket of its own.

### `GenerationMode` (axis 2b — EC/SMC generated together vs separately)
- `EC and SMC co-generated in one protocol`
- `EC and SMC separately generated and combined`
- `EC-only (no SMC/mural population)`
- `Unresolved / not reported`

### `Architecture` (axis 5 — self-organization; kept per explicit confirmation)
- `Self-organized / self-assembled (no scaffold)`
- `Scaffold-guided / bioprinted / templated`
- `Membrane- or channel-based barrier interface`
- `Unresolved / not reported`

### `PerfusionType` (axis 3 — perfusion test type)
- `In vitro only`
- `In vivo only (host-anastomosis; not NAM-relevant)`
- `Both (in vitro + in vivo)`
- `Static / no perfusion demonstrated`
- `Unresolved / not reported`

### `ECMMaterial` (axis 4 — ECM used for seeding; multi-label per paper)
Controlled vocabulary matched by keyword (Collagen I/IV, Fibrin, Matrigel,
Laminin, Entactin, Gelatin/GelMA, Fibronectin, Hyaluronic acid, Alginate,
Decellularized ECM, Silk, PEG-based hydrogel, Basement membrane extract,
Lectin-coated surface, `Other / unspecified`, `Not reported`). A single paper
can use more than one material (e.g. fibrin gel + laminin coating), hence
this is a node type with a one-to-many relationship, not a single property.

`Collagen (type unspecified)` is also a valid vocabulary member, for cases
where a reviewer confirmed the source only says "collagen" without
specifying type I/IV. It is NOT matched by the keyword heuristic itself
(see comment above `_ECM_VOCAB` in `classify.py`) — it can currently only be
assigned via the manual override mechanism below.

## Manual axis-review overrides (Platform type / Architecture / Perfusion / ECM)

On 2026-11-06 the user hand-reviewed Architecture, PerfusionType, and ECM
classifications for 51 of the then-60 papers against the primary literature
(DOI-verified) and supplied corrected values. Rather than rewrite 51 papers'
raw free-text columns to coincidentally retrigger the right keyword-heuristic
bucket, these corrections are stored as explicit override columns on the CSV
and applied by `load_graph.py` ahead of the `classify.*` heuristics. On
2026-11-07 the mechanism was extended to also cover Platform type (see
"Fixed 2026-11-07" below for why):

```
platform_type_override, architecture_override, perfusion_type_override,
ecm_materials_override, axis_review_confidence, axis_review_note
```

- `platform_type_override` / `architecture_override` / `perfusion_type_override`
  — exact controlled-vocabulary string, or blank if the user did not review
  that axis for this paper (heuristic `classify.*` output is kept in that
  case).
- `ecm_materials_override` — `; `-separated list of controlled-vocabulary ECM
  names, or blank (same fallback rule).
- `axis_review_confidence` — `user-confirmed` (34 papers; reviewer read the
  primary source directly) or `provisional` (23 papers; reviewer's best read
  based on available/secondary evidence, not yet independently verified
  against full text). Both tiers are applied to the live graph; the
  confidence tag is preserved on `Paper.axis_review_confidence` and surfaced
  in the embedded evidence text so `ask`/`search` results can note when a
  classification is provisional.
- `axis_review_note` — free-text justification/caveat from the review (e.g.
  P033: "bath perfusion used solely for calcium imaging ... not an internal
  vascular perfusion circuit"; P008: ECM is specifically SpGel-derived
  decellularized ECM). Stored on `Paper.axis_review_note` and included in the
  embedded `EvidenceChunk` text.

See `load_graph.py`'s `apply_axis_overrides()` for the precedence logic.
As of 2026-11-08, papers with no override columns populated at all (P012,
P016, P035, P039, P042, P061) keep their original keyword-heuristic
classification for all four axes above.

### Corpus exclusion (`excluded_from_corpus` / `exclusion_reason`)

Added 2026-11-08 when P026 ("Microgels With Electrostatically Controlled
Molecular Affinity to Direct Morphogenesis") was found, on closer read of
the primary text, to use HUVEC (not iPSC-derived/direct-reprogramming) for
the organoid-vascularization model relevant to this corpus's scope — it no
longer qualifies for inclusion. The row is **not deleted**: `paper_id` is
derived purely from CSV row position (`load_csv_rows()`'s
`enumerate(reader, start=2)`), so physically removing a row would silently
renumber every subsequent paper and invalidate every paper-ID reference
already written into this file and the CSV's own `axis_review_note`
columns. Instead:

```
excluded_from_corpus, exclusion_reason
```

- `excluded_from_corpus` — `"TRUE"` or blank. `load_graph.py` filters these
  rows out immediately after assigning `_row_id` (so IDs for every other
  row are unaffected) and before anything else runs, including `--limit`.
- `exclusion_reason` — free-text explanation, kept for audit trail even
  though the row never reaches the graph.

Excluded rows still count toward the CSV's 60 total rows but not toward the
59 retained/live papers quoted throughout this file and the READMEs.

### `EvidenceChunk` (one per paper; the embedded/vector-searchable node)
```
paper_id, doi, text, embedding (float[1536])
```
`text` is a short, structured synthesis built ONLY from the five axes above
plus their raw snippets (truncated) — not the full original batch-report
paragraph, which contained a lot of reviewer/process narrative irrelevant to
the actual research questions. This keeps each embedded chunk small and
on-topic, e.g.:

```
Paper P054 (2020): Adaptable haemodynamic endothelial cells for organogenesis and tumorigenesis
Platform: Chip / microfluidic device
Vasculature cell source: Direct reprogramming (incl. EC-to-EC resetting, e.g. ETV2 on mature EC) | Generation mode: EC-only (no SMC/mural population)
Architecture: Self-organized / self-assembled (no scaffold)
Perfusion: Both (in vitro + in vivo)
ECM/matrix: Fibrin, Laminin
```

## Relationships

```
(Paper)-[:HAS_PLATFORM_TYPE]->(PlatformType)
(Paper)-[:USES_CELL_SOURCE]->(CellSource)
(Paper)-[:HAS_GENERATION_MODE]->(GenerationMode)
(Paper)-[:HAS_ARCHITECTURE]->(Architecture)
(Paper)-[:HAS_PERFUSION_TYPE]->(PerfusionType)
(Paper)-[:USES_ECM]->(ECMMaterial)        -- zero or more per paper
(Paper)-[:HAS_EVIDENCE]->(EvidenceChunk)  -- exactly one per paper
```

No `Journal` node, no `ModelCategory` node, no `ReprogrammingMethod` node —
journal title is a `Paper` property (identity metadata, not a traversal
axis you asked for), and the named reprogramming factor (e.g. "ETV2") lives
in `Paper.reprogramming_factor_raw` since it's highly variable free text
rather than a small controlled vocabulary worth a graph node.

## Vector index

```
CREATE VECTOR INDEX evidence_embedding IF NOT EXISTS
FOR (e:EvidenceChunk) ON (e.embedding)
OPTIONS { indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}}
```

## Why this shape

The five category nodes turn exactly the dimensions you said matter
(platform, cell source + generation mode, self-organization, perfusion
type, ECM) into graph axes you can intersect directly in Cypher — e.g.
"self-organized AND in-vitro-perfused AND direct-reprogrammed AND EC/SMC
co-generated" is the precise novelty intersection for your background
section, expressible as a single filtered MATCH. Layering the vector index
on top of `EvidenceChunk` (built from exactly those same five axes) lets
`query_rag.py` do semantic retrieval ("find papers about long-term in vitro
vessel maintenance") without re-ingesting irrelevant text, since the
embedded content was never bloated with it in the first place.

## Known data caveats (carried over from the CSV)

- Rows 62, 66, 74 are provisional retentions based on secondary-source
  evidence.
- Row 12 may not have an authored EC/vascular component (host-mouse-derived
  vascularization post-transplant) — flagged in `cell_identity_evidence`
  review, not represented specially in this lean schema.
- Row 18's cited article URL may be mismatched — not re-verified here.
- Classification into the five axes is rule-based (`classify.py`); raw CSV
  fields are retained on `Paper` so misclassifications can be traced back
  and the keyword rules corrected.
- Architecture, PerfusionType, and ECM for 54/59 papers are manual
  reviewer overrides (see "Manual axis-review overrides" above), not
  keyword-heuristic output; 20 of those 54 are tagged `provisional`
  (`Paper.axis_review_confidence`) pending full-text verification.
- **Fixed 2026-11-06**: `classify_architecture`/`classify_perfusion_type` had
  a false-positive bug — a recurring screening-note header,
  `"EC-origin/self-assembly/flow verification pass (5 Nov 2026): ..."`,
  contains the literal field label "self-assembly", which the keyword
  heuristic matched as a positive "self-organized" signal even when the
  actual verdict immediately following the header was "Not self-organized."
  Fixed by stripping the header (`_strip_boilerplate` in `classify.py`)
  before classification. This flipped 9 papers from a wrong "Self-organized"
  to the honest "Unresolved / not reported" (5 of which already had a manual
  override that wins regardless: P018, P019, P022, P028, P030). The 3 with
  no override were resolved with the user's input: P032, P040, P060 were set
  to "Membrane- or channel-based barrier interface" (provisional) based on
  the raw screening evidence (ECs manually seeded onto a pre-fabricated
  channel/flat surface, not self-organized). P013 was left as the user's
  original "Self-organized" table entry, despite its raw screening note
  reading "host-driven vascularization, not a self-assembled EC construct" —
  the user explicitly chose to keep the user-confirmed table value over the
  older, narrower screening note.
- **Resolved 2026-11-07**: the user independently re-verified all 9 papers
  from the fix above against the primary literature and confirmed/corrected
  each; all 9 are now `axis_review_confidence = user-confirmed`:
  - P013, P018, P019, P028 — confirmed "Self-organized / self-assembled"
    is correct: vascularization occurs simultaneously during organoid
    generation (not host-driven, contra the narrower screening note).
  - P022 — confirmed "Membrane-based"; vascular (bottom) channel is coated
    with collagen IV:water:fibronectin (4:5:1), top neural channel with
    Matrigel; pump-driven in vitro perfusion (5.88 uL/hr).
  - P030 — confirmed "Membrane-based" (ultra-thin nanomembrane, uSiM)
    coated with collagen IV (400 ug/mL) + bovine fibronectin (100 ug/mL);
    perfusion corrected from unset to "Static / no perfusion demonstrated"
    (authors explicitly state static conditions).
  - P032 — confirmed "Membrane-based"; ECM resolved from unset to
    Collagen IV + Fibronectin (uSiM channel coating); perfusion resolved
    from unset to "In vitro only" (pump-driven peristaltic flow, 0.5 Pa
    shear, 48h). Promoted from provisional to user-confirmed.
  - P040 — confirmed "Membrane-based"; ECM resolved from "Not reported" to
    "Gelatin / GelMA" (0.1% gelatin-coated channel, device-guided seeding,
    not pre-vascularized). Promoted from provisional to user-confirmed.
  - P060 — confirmed "Membrane-based"; ECM corrected from an earlier
    Matrigel/Fibrin guess to "Collagen (type unspecified)" (EC monolayer
    seeded on a collagen gel layer, 5.0x10^5 cells/mL); perfusion resolved
    to "Static / no perfusion demonstrated" (EC layer is a static BBB-like
    diffusion barrier). Promoted from provisional to user-confirmed.
- **Fixed 2026-11-07**: a second `_contains_unnegated` false-positive bug —
  the negation-word list (`"not "`, `"n't "`, `"without "`, `"lacking "`)
  didn't include bare `"no "`, so text like "...no clean self-organized
  patient vascular model" (P049's screening notes) or "...self-assembled
  vascular networks/sprouting, no scaffold" (P025, P061's architecture
  assessment) was read as an unnegated positive hit on whichever marker
  came right after "no". Fixed by adding a tight 15-character lookback
  check for `"no "` (kept separate and much shorter than the 40-character
  window the other negation words use, since "no" is common enough in free
  text that a wide window risked suppressing unrelated true positives
  elsewhere). Found by the user directly reading P049's methods ("microdevice
  featuring a silicon-nitride membrane") and noticing its graph label
  ("Self-organized") didn't match. A full before/after diff across all 60
  rows showed the fix flips Architecture for 7 papers:
  - P025, P061 — were wrongly "Scaffold-guided" (the bug read "no scaffold"
    as a positive scaffold-marker hit); now correctly resolve to
    "Self-organized" via the heuristic alone, with no override needed —
    both papers' raw text explicitly and unambiguously states "no
    scaffold."
  - P010, P011, P020, P026 — same wrong-direction flip, but all four
    already carry a manual `architecture_override` that wins regardless,
    so this bug never affected their live graph value.
  - P049 — was wrongly "Self-organized" (the bug missed the negation in
    "no clean self-organized..."); the fix alone only gets it to
    "Unresolved," since the classifier doesn't read the `matrix` field at
    all. Set via a new override to "Membrane- or channel-based barrier
    interface" (user-confirmed) based on the `matrix` field and the
    paper's own description of a silicon-nitride-membrane microdevice —
    the μSiM platform's defining feature.
- **Fixed 2026-11-07**: `classify_platform_type` read `model_category_raw`
  — a coarse, 5-bucket screening-stage label (e.g. "Vascular chip /
  engineered vascular tissue" shared verbatim by 18 of the then-60 papers) — as
  if it were paper-specific evidence. The user caught this on P018
  (organoid transplanted into a mouse, no chip/device anywhere, but labeled
  "Chip / microfluidic device" solely because its generic `model_category`
  bucket happened to contain the word "chip"). A full-corpus diff confirmed
  6 papers' chip/organoid signal came *only* from this generic label.
  Fixed by dropping `model_category` from the scanned text entirely and
  scanning `article_title` instead/in addition (short, specific, often
  decisive — e.g. "Artery-on-Chip...", "...multi-organoid-on-a-chip...").
  `model_category_raw` is still stored on `Paper` for audit, just no longer
  used for classification. This flips PlatformType for 7 papers, all
  towards more accurate (every case independently checked against raw
  evidence moved the right direction):
  - P007 — "Organoid" -> "Organoid-on-chip / hybrid" (title literally says
    "multi-organoid-on-a-chip").
  - P022 — "Organoid" -> "Organoid-on-chip / hybrid" (title says
    "organ-chip"; also consistent with this paper's already-confirmed
    Architecture override — "manually seeded into pre-fabricated
    microfluidic channel").
  - P012, P023, P035 — "Organoid-on-chip / hybrid" -> "Organoid (no
    chip/device)" (no chip evidence anywhere in paper-specific text; P035's
    `culture_dish_or_chip` raw field explicitly says well-plate culture).
  - P017 — "Chip / microfluidic device" -> "Unresolved / not reported" (no
    chip evidence anywhere in paper-specific text; the available evidence
    is genuinely ambiguous, so Unresolved is the honest call rather than a
    confident guess).
  - P018 — "Chip / microfluidic device" -> "Unresolved / not reported" via
    the heuristic alone (still no paper-specific "organoid" keyword in the
    scanned fields). Per the user's explicit correction, set via a new
    `platform_type_override` (the mechanism was extended to cover Platform
    type for this) to "Organoid (no chip/device)", user-confirmed — BVO
    (blood-vessel-organoid)-based pericyte-enriched vascular assembly,
    generated in vitro then transplanted into mouse brain.
- **Corrected 2026-11-07**: P005 ("Cell body area expansion is a key factor
  determining connectivity and diameter of on-chip vascular networks") —
  Platform type and Architecture were already correct (Chip, Self-organized,
  both heuristic-derived, no override needed). Two overrides corrected
  against the user's direct read of the primary methods:
  - ECM: "Collagen (type unspecified)" -> "Collagen I" (paper specifies
    "neutralized collagen type I (Corning)").
  - Perfusion: "In vitro only" -> "Static / no perfusion demonstrated" (on
    closer check, the device is a chamber perfused with different media
    formulations to compare self-organization outcomes, not a continuous
    flow-through system — no lumen-perfusion/flow test was actually
    performed, despite the paper's "on-chip" framing).
  - CellSource kept as "iPSC-derived" per user's explicit choice, with a
    note added that the paper also tests primary ECs (HUVEC, HBMEC) as
    comparator baselines alongside the iPSC-EC (M-/B-iPSC-EC) condition
    that is actually relevant to this corpus's scope.
  Also investigated, not a bug: P054 (Rafii-lab R-VEC paper, "Adaptable
  haemodynamic endothelial cells for organogenesis and tumorigenesis") is
  Self-organized + In-vitro-perfused (heuristic got both right already, no
  override needed), but PlatformType is "Organoid-on-chip / hybrid" (its
  methods explicitly describe organoid co-culture alongside the vascular
  chip) rather than pure "Chip", and CellSource is "Other" by design — see
  the `_OTHER_MARKERS` comment above `classify_cell_source` and the
  "Retained by user as Rafii comparator... not confirmed eligible core"
  screening note: R-VEC is ETV2-mediated EC-to-EC resetting, not a genuine
  lineage conversion from a non-vascular somatic cell and not iPSC-derived,
  so it's intentionally excluded from the direct-reprogramming novelty
  intersection rather than missing a tag.
- **Corrected 2026-11-07 (same day, follow-up)**: the user pushed back that
  P054 and P009 should both be pure "Chip", not "Organoid-on-chip /
  hybrid" — and was right. Checked both papers' actual published
  abstracts (bioRxiv preprint for P009, Palikuqi et al. 2020 Nature for
  P054): both separately describe (a) a self-organized, blood/dextran-
  perfused vascular network built directly in a microfluidic
  chip/chamber, and (b) a secondary, separately-described capability of
  that same chip vasculature vascularizing/co-culturing with various
  organoids or tissues (liver organoid for P009; pancreatic islets,
  decellularized intestine, colon organoids/tumoroids for P054). The
  "Organoid-on-chip / hybrid" heuristic call was treating (b) as changing
  the platform type of (a), when the vascular architecture itself (the
  axis this corpus actually cares about) is purely chip-based in both
  cases — the organoid is a downstream perfusion target, not the
  structure being classified. Set `platform_type_override` to "Chip /
  microfluidic device" (user-confirmed) for both, consistent with their
  already-correct "Self-organized" / "In vitro only" axis values. This is
  a general lesson for any other paper where methods text mentions both
  "chip" and "organoid": check whether the organoid is the vasculature's
  own architecture, or a separate tissue the chip-based vasculature
  connects to/perfuses — the keyword heuristic cannot make that
  distinction and will over-call "hybrid".
- **Fixed 2026-11-08**: while triaging the rest of the "Organoid-on-chip /
  hybrid" bucket for the P009/P054 pattern above, found that
  `classify_platform_type` had zero negation awareness at all (a plain
  `in text` substring check, unlike the architecture/perfusion/cell-source
  classifiers elsewhere in this file) — so text explicitly denying a chip
  was read as confirming one. Two confirmed cases: P061's
  `culture_dish_or_chip` says "no microfluidic chip (organoid protocol)";
  P034's says "No perfused chip circuit demonstrated in this study." Fixed
  by routing `has_chip`/`has_organoid` through `_contains_unnegated` like
  the other classifiers. This also exposed that the existing tight 15-char
  `no_window` (added for the P049 fix on 2026-11-07) was too short for "no
  microfluidic chip" — one adjective between "no" and the negated noun
  pushed it just past the boundary — so `no_window` widened 15 -> 25. A
  full corpus diff confirmed this only flips P034 and P061 (both
  "Organoid-on-chip / hybrid" -> "Organoid (no chip/device)", both correct,
  neither had an existing override) and causes zero side effects on
  Architecture or CellSource (which also use `_contains_unnegated`).
- **Reviewed 2026-11-08**: went through the rest of the "Organoid-on-chip /
  hybrid" bucket the user had asked to be triaged, confirming no further
  classifier code changes were needed — these were per-paper judgment
  calls, not bugs:
  - P027 — no change. Architecture was already correctly
    "Scaffold-guided" via an existing override (the sVEB vessel structure
    is scaffold-based, not self-organized), and the "hybrid" platform-type
    call is genuinely correct here, unlike P009/P054: the tumor organoid
    is assembled directly in a hydrogel compartment around and attached to
    the sVEB as an integral, deliberate two-component design, not a
    separate downstream target the way P009/P054's organoid applications
    were.
  - P014 — platform type and architecture confirmed correct as-is
    (hybrid; self-organized EC network in a central channel, organoid
    added to vascularize). Perfusion corrected from "In vitro only" to
    "Static / no perfusion demonstrated" per the user's direct check: no
    flow system is used; perfusability was only checked via lectin
    staining, not a flow/gravity-driven test.
  - P026 — **excluded from the corpus** (see "Corpus exclusion" above).
    The user's direct read of the primary paper (Kuhn et al., Adv. Mater.
    2024) found the organoid-vascularization model relevant to this
    corpus's scope uses HUVEC, not iPSC-derived or direct-reprogrammed
    cells, so it no longer meets the inclusion criteria in the top-level
    README. Separately, this row's prior override data (claiming
    "CRTD3i003-B kidney organoid," "OrganoPlate Graft" perfusion, and a
    chorioallantoic membrane assay) could not be corroborated against the
    actual paper via two independent web searches and directly
    contradicted the user's own read — it was likely mis-attributed from
    elsewhere at some earlier point and has been cleared from the row
    rather than carried forward.
  - P038 — Architecture ("Self-organized") and Perfusion ("Static") were
    already correct via the heuristic alone. Platform type corrected via a
    new override from "Organoid-on-chip / hybrid" to pure "Organoid (no
    chip/device)" (user-confirmed): no chip, no perfusion, kidney organoid
    self-assembles with spontaneous vasculogenesis-like fusion. Same
    boilerplate-methods-sentence false signal as the P009/P054/P054-class
    bugs above.
  - P046 — Architecture ("Scaffold-guided") and Perfusion ("In vitro
    only") were already correct via existing overrides; the user's read
    added the precise flow-rate evidence (6 uL/h through both side
    channels, 3 dynes/cm^2 wall shear stress, up to 72h) now folded into
    the note. Platform type corrected via a new override from
    "Organoid-on-chip / hybrid" to pure "Chip / microfluidic device"
    (user-confirmed): EC lines a PDMS channel (scaffold/channel-guided,
    not self-organized, not organoid-based at all). Same boilerplate
    methods sentence as the false signal source.
  - P058 — Architecture ("Scaffold-guided") and Perfusion ("In vitro
    only") were already correct via existing overrides (EC seeded on the
    scaffold-defined channel surface; media flowed through the luminal
    space, pressure/rate unspecified in available text). Platform type
    corrected via a new override from "Organoid-on-chip / hybrid" to pure
    "Chip / microfluidic device" (user-confirmed) — no organoid at all,
    same boilerplate-methods false signal.
  - P007, P050, P055 — reviewed and confirmed correct as-is, no changes:
    all three are genuine hybrids where the organoid is pre-vascularized
    (self-organized or scaffold-guided) during generation and then placed
    into/onto a chip with applied flow — unlike the P009/P054 pattern,
    the organoid IS the vascularized structure here, not a separate
    downstream target.
  - P042 — Architecture (Self-organized), Perfusion (Static), and ECM
    (PEG-based hydrogel) were already correct via the heuristic alone — the
    raw evidence text is explicit that "flow" here refers only to the
    microfluidic droplet-generation device used to fabricate the hydrogel-
    microcapsule organoid, not perfusion through a vascular lumen. Platform
    type corrected via a new override from "Organoid-on-chip / hybrid" to
    pure "Organoid (no chip/device)" (user-confirmed): the "microfluidic"
    keyword was matching the organoid-fabrication method, not a culture/
    assay platform the organoid lives on.
  - P022 — Architecture, Perfusion, and ECM were already correct via the
    overrides set earlier (see the P013/P018/.../P060 review above).
    Platform type corrected via a new override from "Organoid-on-chip /
    hybrid" to pure "Chip / microfluidic device" (user-confirmed),
    consistent with the already-confirmed Membrane-based architecture: EC
    seeded on a porous membrane in a pre-fabricated microfluidic channel,
    no organoid involved.

  This closes out the "Organoid-on-chip / hybrid" triage the user
  requested on the original 13 papers (P007, P014, P022, P026, P027, P034,
  P038, P042, P046, P050, P055, P058, P061):
  - 1 excluded entirely (P026, see above).
  - 2 auto-fixed by the `classify_platform_type` negation bug fix alone,
    no override needed (P034, P061 -> pure Organoid).
  - 5 corrected via new `platform_type_override`s to pure Chip or pure
    Organoid (P022, P038, P042, P046, P058).
  - 5 confirmed genuinely correct hybrids after review, no change
    (P007, P014, P027, P050, P055).
  (P009 and P054 were corrected in a separate, earlier exchange about the
  Rafii/ETV2 papers specifically — not part of this 13-paper list, though
  the same root issue applied.) `axis_review_confidence` is now 34
  `user-confirmed` / 20 `provisional` (54/59 papers reviewed overall).
