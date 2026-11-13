"""
Heuristic, transparent keyword classifiers that normalize the free-text
CSV columns into the controlled vocabularies used as graph node names.

Scope is deliberately narrow: only the axes the user identified as relevant
to the research question are classified here —
  1. platform type (chip vs organoid)
  2. vasculature cell source + generation mode (iPSC-derived vs direct
     reprogramming; EC/SMC co-generated in one protocol vs separately
     generated and combined vs EC-only)
  3. self-organization / scaffold-free architecture (kept as a 5th axis
     per explicit user confirmation — central to the novelty argument)
  4. perfusion type (in vitro / in vivo / both)
  5. ECM/matrix material(s) used for seeding (multi-label)

No ML here on purpose: the rules are explicit so you can see exactly why a
paper landed in a given bucket, and the raw source text is always kept on
the Paper node for audit.
"""
from __future__ import annotations

UNRESOLVED = "Unresolved / not reported"


def _norm(*parts: str) -> str:
    return " || ".join(p for p in parts if p).lower()


import re as _re

# A recurring literature-review header, e.g. "EC-origin/self-assembly/flow
# verification pass (5 Nov 2026): Not self-organized - ...", was prepended to
# `vascular architecture assessment` for ~30 rows during a later review pass.
# The header itself contains "self-assembly" and "flow" as generic field
# labels, not as a claim about the paper — but those are exactly the keyword
# markers `classify_architecture`/`classify_perfusion_type` look for, so the
# header was spuriously tripping a "Self-organized" match even on rows whose
# actual verdict (right after the header) was "Not self-organized" (e.g.
# P060, P032, P040, P036 before this fix). Strip it before classifying.
_BOILERPLATE_HEADER_RE = _re.compile(
    r"ec-origin/self-assembly/flow verification pass\s*\([^)]*\):\s*"
)


def _strip_boilerplate(text: str) -> str:
    return _BOILERPLATE_HEADER_RE.sub("", text)


def _contains_unnegated(text: str, phrase: str, window: int = 40, no_window: int = 25) -> bool:
    """True if `phrase` occurs in `text` without a negation word (e.g. 'not',
    'NOT') immediately before it. Review text in this corpus frequently reads
    like '...iPSC-derived EC/SMC...; not direct reprogramming.' — a naive
    substring match on 'direct reprogram' would wrongly flag that as a
    positive hit, so every occurrence must be checked for a preceding
    negation within a short window.

    'no ' is checked separately with a much tighter window (`no_window`):
    it's common enough in free text that an unrelated 'no' earlier in a long
    sentence (e.g. 'no issues were found; the vessels self-organized...')
    could wrongly suppress a true positive at the full 40-char window, but a
    close 'no' (e.g. 'no clean self-organized patient vascular model') is a
    real negation worth catching."""
    search_start = 0
    while True:
        idx = text.find(phrase, search_start)
        if idx == -1:
            return False
        prefix = text[max(0, idx - window):idx]
        near_prefix = text[max(0, idx - no_window):idx]
        negated = (
            "not " in prefix or "n't " in prefix or "without " in prefix or "lacking " in prefix
            or "no " in near_prefix
        )
        if not negated:
            return True
        search_start = idx + len(phrase)


# ---------------------------------------------------------------------------
# 1. Platform type: chip assay vs organoid
# ---------------------------------------------------------------------------
def classify_platform_type(culture_dish_or_chip: str, methods: str, article_title: str) -> str:
    """`model_category` is deliberately NOT scanned here: it's a coarse,
    5-bucket screening-stage label (e.g. "Vascular chip / engineered
    vascular tissue" shared verbatim by 18 papers), not paper-specific
    evidence — keyword-matching against it is the same class of bug as the
    boilerplate-header issue fixed elsewhere in this file. A diff across
    the corpus confirmed it was producing false "Chip" hits (e.g. P018, an
    organoid transplanted into a mouse with no chip/device at all) and
    false "Organoid-on-chip" hits for papers with zero actual chip
    evidence. `article_title` is scanned instead/in addition — it's
    short, specific, and often decisive (e.g. "Artery-on-Chip...",
    "...multi-organoid-on-a-chip...").
    """
    text = _norm(culture_dish_or_chip, methods, article_title)
    if not text.strip():
        return UNRESOLVED

    chip_markers = ["chip", "microfluidic", "pdms", "device", "channel", "bioreactor circuit"]
    organoid_markers = ["organoid"]

    # Negation-aware: this corpus's review text includes explicit negative
    # statements like "no microfluidic chip (organoid protocol)" (P061) or
    # "No perfused chip circuit demonstrated in this study" (P034) — a plain
    # substring check on "chip" wrongly flags both as chip-containing.
    has_chip = any(_contains_unnegated(text, m) for m in chip_markers)
    has_organoid = any(_contains_unnegated(text, m) for m in organoid_markers)

    if has_chip and has_organoid:
        return "Organoid-on-chip / hybrid"
    if has_chip:
        return "Chip / microfluidic device"
    if has_organoid:
        return "Organoid (no chip/device)"
    return UNRESOLVED


# ---------------------------------------------------------------------------
# 2a. Vasculature cell source — 5-bucket schema per explicit user correction
#     (2026-11-06, revised again same day): iPSC-derived / Direct
#     reprogramming / Mix / Other / Unresolved.
#
#     REVISION HISTORY on "Direct reprogramming" vs. ETV2-style "resetting":
#     earlier the same day, the user asked to MERGE ETV2-mediated resetting
#     of an already-mature EC (the Rafii-lab R-VEC paper, row 54/P054) into
#     "Direct reprogramming". After reviewing the paper again, the user
#     explicitly reversed that: R-VEC is NOT true direct reprogramming (it
#     never leaves the EC lineage — a mature, already-differentiated EC is
#     transcriptionally "reset" into a more plastic EC state via ETV2, not
#     converted from a non-vascular somatic cell into an EC) and should be
#     flagged as its own "Other" bucket instead. So the two concepts are
#     SPLIT AGAIN:
#       - "Direct reprogramming" = true transdifferentiation: a non-vascular,
#         non-pluripotent somatic cell (e.g. fibroblast) is converted
#         directly into an EC/SMC, bypassing a pluripotent-stem-cell
#         intermediate entirely.
#       - "Other" = cases that don't fit the iPSC-vs-direct-reprogramming
#         dichotomy at all — currently just ETV2-style EC-to-EC "resetting"
#         of an already-mature EC (R-VEC-style), which is neither iPSC-
#         differentiated nor a genuine lineage conversion from a non-vascular
#         cell.
#
#     "Mix" = within one paper, the EC population and the non-EC/mural
#     population (SMC/pericyte/macrophage) are sourced by DIFFERENT methods
#     (e.g. EC is iPSC-derived but the pericytes/SMC are primary cells).
#     Detected via the same semicolon-segment heuristic used in
#     classify_generation_mode(), comparing the origin type resolved for the
#     EC-mentioning segment(s) vs the non-EC-mentioning segment(s).
#
#     hESC: per user instruction, a paper using ONLY hESC (no iPSC mention at
#     all) gets no dedicated bucket and falls to Unresolved. If iPSC is
#     mentioned anywhere (even alongside hESC), the paper is iPSC-derived and
#     the hESC mention is irrelevant.
# ---------------------------------------------------------------------------
_IPSC_MARKERS = [
    "ipsc", "hipsc", "induced pluripotent", "hpsc", "human pluripotent stem cell",
    "psc-derived", "psc18",
]
# These phrases are frequently NEGATED in this corpus's review text (e.g.
# "...iPSC-derived EC/SMC...; not direct reprogramming."), so every check
# against this list must be negation-aware rather than a bare substring test.
# NOTE: genuine transdifferentiation markers ONLY — ETV2-style resetting of
# an already-mature EC is intentionally NOT here (see _OTHER_MARKERS below
# and the revision-history note above): it was briefly merged into this
# bucket, then explicitly split back out per user correction.
_DIRECT_REPROG_MARKERS = [
    "direct reprogram", "directly reprogram", "transdifferen", "direct conversion",
    "directly converted", "somatic-to-ec", "fibroblast-to-ec", "fibroblast-derived ec",
    "without passing through",
]
# "Other" bucket: currently just ETV2-mediated transcriptional resetting of
# an already-mature/already-differentiated EC into a more plastic EC state
# (e.g. R-VEC) — EC-to-EC, not a lineage conversion from a non-vascular cell,
# and not iPSC-derived either.
_OTHER_MARKERS = [
    "resetting", "reset mature", "r-vec", "etv2-mediated transcriptional resetting",
]
_HESC_MARKERS = ["hesc", "embryonic stem cell", "esc-derived", "hes3", "hes2", "h9 "]
# NOTE: deliberately no bare "primary" or "commercial" keyword — this
# corpus's review text uses "primary"/"commercial" for many unrelated senses
# ("primary literature source", "Commercial iCell iPSC-derived ECs" — itself
# an iPSC product, not a primary cell), which caused false positives here.
_PRIMARY_MARKERS = [
    "huvec", "sciencell", "hmvec", "hcaec", "haec", "homec",
    "umbilical vein", "cord blood", "blood outgrowth", "primary human",
    "primary ec", "primary endothelial", "primary culture", "primary isolat",
    "primary artery", "primary vein cell",
]
_EC_SEGMENT_MARKERS = ["ec", "endothelial"]
_NON_EC_SEGMENT_MARKERS = ["smc", "smooth muscle", "smooth-muscle", "mural", "pericyte", "macrophage"]


def _cell_source_origin(text: str) -> str | None:
    """Classify a text segment's cell-of-origin method: 'direct_reprogramming'
    / 'other_resetting' / 'ipsc' / 'primary' / None (not enough signal, or
    hESC-only which has no bucket of its own). Order matters: the most
    specific/deliberate claims are checked first since some text explicitly
    contrasts one against another (e.g. "iPSC-derived progenitors, not direct
    reprogramming", "still iPSC-derived, NOT direct reprogramming from a
    non-vascular somatic cell")."""
    if any(_contains_unnegated(text, m) for m in _DIRECT_REPROG_MARKERS):
        return "direct_reprogramming"
    if any(_contains_unnegated(text, m) for m in _OTHER_MARKERS):
        return "other_resetting"
    if any(m in text for m in _IPSC_MARKERS):
        return "ipsc"
    if any(m in text for m in _HESC_MARKERS):
        return None  # hESC-only -> no bucket, falls to Unresolved
    if any(m in text for m in _PRIMARY_MARKERS):
        return "primary"
    return None


def classify_cell_source(ec_source_assessment: str, cell_type: str, reprogramming_factor: str) -> str:
    """Return one normalized CellSource bucket: iPSC-derived / Direct
    reprogramming / Mix / Other / Unresolved."""
    combined_text = _norm(ec_source_assessment, cell_type, reprogramming_factor)
    if not combined_text.strip():
        return UNRESOLVED

    # Segment-based split (mirrors classify_generation_mode) so the EC
    # population's origin can be compared against any SMC/mural/pericyte/
    # macrophage population's origin, since a paper can source them
    # differently (e.g. iPSC-derived EC + primary pericytes).
    raw_segments_source = " ; ".join(p for p in [ec_source_assessment, cell_type] if p)
    segments = [s.strip().lower() for s in raw_segments_source.split(";") if s.strip()]

    # Priority (not first-match-wins) when multiple EC-tagged segments give
    # conflicting signals. Rationale: some papers describe a primary
    # iPSC/direct-reprogramming-derived vascularized model AND mention a
    # separate commercial/primary-cell (e.g. HUVEC) comparator or control arm
    # in the same free-text blob. "HUVEC" itself contains the substring "ec",
    # so it trips the EC-segment marker regardless of whether it's the
    # paper's actual model or just a side comparator. A specific, deliberate
    # iPSC/direct-reprogramming mention is stronger evidence of the paper's
    # real EC source than a generic "primary" hit, so it should win no matter
    # which segment happens to appear first in the text (confirmed against
    # P026/P056, where the HUVEC comparator-arm segment preceded the true
    # iPSC-kidney-organoid segment and was incorrectly winning under plain
    # first-match-wins).
    _ORIGIN_PRIORITY = {"primary": 0, "ipsc": 1, "other_resetting": 2, "direct_reprogramming": 3}
    ec_origin = None
    ec_origin_priority = -1
    non_ec_origin = None
    for seg in segments:
        is_ec_seg = any(m in seg for m in _EC_SEGMENT_MARKERS)
        is_non_ec_seg = any(_contains_unnegated(seg, m) for m in _NON_EC_SEGMENT_MARKERS)
        seg_origin = _cell_source_origin(seg)
        if seg_origin is None:
            continue
        if is_ec_seg:
            prio = _ORIGIN_PRIORITY.get(seg_origin, -1)
            if prio > ec_origin_priority:
                ec_origin = seg_origin
                ec_origin_priority = prio
        if is_non_ec_seg and non_ec_origin is None:
            non_ec_origin = seg_origin

    # Fallback: segment splitting found no resolvable EC-specific origin
    # (e.g. no semicolons at all, or EC markers absent from every segment) —
    # classify the whole blob instead.
    if ec_origin is None:
        ec_origin = _cell_source_origin(combined_text)

    if ec_origin is not None and non_ec_origin is not None and ec_origin != non_ec_origin:
        return "Mix (EC and non-EC/mural cells sourced differently)"
    if ec_origin == "direct_reprogramming":
        return "Direct reprogramming (non-vascular somatic cell -> EC/SMC, bypasses pluripotency)"
    if ec_origin == "other_resetting":
        return "Other (e.g. ETV2-mediated resetting of an already-mature EC; EC-to-EC, not iPSC-derived, not a lineage conversion from a non-vascular cell)"
    if ec_origin == "ipsc":
        return "iPSC-derived"
    return UNRESOLVED


# ---------------------------------------------------------------------------
# 2b. Generation mode: EC+SMC co-generated together vs separately generated
#     and combined vs EC-only (no SMC/mural population at all)
# ---------------------------------------------------------------------------
def classify_generation_mode(
    ec_source_assessment: str, cell_type: str, screening_notes: str, article_title: str = ""
) -> str:
    """Three-way split: EC-only (no SMC/mural at all) / separately generated
    and combined / co-generated in one protocol.

    This corpus's review text almost never uses explicit phrasing like
    "co-differentiated" — instead it just lists the populations, e.g.
    "mesodermal progenitors -> CD31+ EC / alpha-SMA+ mural cells" (a single
    differentiation branching into both lineages: co-generated) vs.
    "hiPSC-derived ECs; hPSC-derived cardiomyocytes/SMCs; human cardiac
    fibroblasts" (semicolon-separated, independently-sourced populations
    assembled into a multi-cell-type chip: separately generated). So besides
    explicit keyword markers, a segment-based heuristic is used: split the
    raw EC-source/cell-type text on ';' and check whether EC and SMC/mural/
    pericyte mentions fall in the SAME segment (co-generated) or DIFFERENT
    segments (separately generated and combined). Flag genuinely ambiguous
    cases by checking Paper.ec_source_assessment_raw / cell_type_raw directly.
    """
    combined_text = _norm(ec_source_assessment, cell_type, screening_notes, article_title)
    if not combined_text.strip():
        return UNRESOLVED

    smc_markers = ["smc", "smooth muscle", "smooth-muscle", "mural", "pericyte"]
    # Negation-aware: comparative text like "not self-organized EC-SMC bed"
    # (contrasting against some OTHER paper's capability) must not be read as
    # "this paper has an SMC population."
    has_smc_mention = any(_contains_unnegated(combined_text, m) for m in smc_markers)

    ec_only_explicit_markers = [
        "ec-only", "ec only", "no smc", "no mural", "no sm c", "no pericyte",
        "no mural/smc/pericyte", "no smc/mural/pericyte", "ec-only construct",
    ]
    if any(m in combined_text for m in ec_only_explicit_markers) or not has_smc_mention:
        return "EC-only (no SMC/mural population)"

    separately_generated_markers = [
        "separately generat", "independently generat", "co-cultured", "co-culture",
        "tri-culture", "triculture", "multi-culture", "multiculture",
        "combined with", "added smc", "added pericyte", "mixed with", "recombined",
        "assembled from separately", "mural cells were added", "separately differentiat",
    ]
    if any(m in combined_text for m in separately_generated_markers):
        return "EC and SMC separately generated and combined"

    # Segment heuristic: does EC co-occur with SMC/mural/pericyte in the SAME
    # semicolon-separated clause (one shared differentiation description), or
    # only in DIFFERENT clauses (independently sourced populations)?
    raw_segments_source = " ; ".join(p for p in [ec_source_assessment, cell_type] if p)
    segments = [s.strip().lower() for s in raw_segments_source.split(";") if s.strip()]
    if len(segments) > 1:
        ec_markers = ["ec", "endothelial"]
        ec_segment_idxs = {i for i, seg in enumerate(segments) if any(m in seg for m in ec_markers)}
        smc_segment_idxs = {
            i for i, seg in enumerate(segments)
            if any(_contains_unnegated(seg, m) for m in smc_markers)
        }
        if ec_segment_idxs and smc_segment_idxs:
            if ec_segment_idxs.isdisjoint(smc_segment_idxs):
                return "EC and SMC separately generated and combined"
            return "EC and SMC co-generated in one protocol"

    # Default: EC and SMC/mural/pericyte mentioned together (single
    # unsegmented description) without explicit multi-culture-assembly
    # language => assumed to arise from one shared differentiation protocol.
    return "EC and SMC co-generated in one protocol"


# ---------------------------------------------------------------------------
# 3. Architecture: self-organized/scaffold-free vs scaffold-guided
#    (kept as an explicit 5th axis per user confirmation)
# ---------------------------------------------------------------------------
def classify_architecture(vascular_architecture_assessment: str, screening_notes: str) -> str:
    text = _strip_boilerplate(_norm(vascular_architecture_assessment, screening_notes))
    if not text.strip():
        return UNRESOLVED

    self_organized_markers = ["self-organiz", "self-assembl", "spontaneous", "de-novo lumen", "de novo lumen"]
    scaffold_markers = [
        "scaffold", "bioprint", "template", "predefined channel", "pre-defined channel",
        "pre-drilled", "channel-templated", "photolithograph", "microfabricat",
        "endothelializing a predrilled", "preprinted lumen",
    ]
    membrane_markers = ["membrane-based", "channel-templated barrier", "porous membrane", "membrane interface"]

    is_self = any(_contains_unnegated(text, m) for m in self_organized_markers)
    is_scaffold = any(_contains_unnegated(text, m) for m in scaffold_markers)
    is_membrane = any(_contains_unnegated(text, m) for m in membrane_markers)

    if is_self and not is_scaffold:
        return "Self-organized / self-assembled (no scaffold)"
    if is_scaffold:
        return "Scaffold-guided / bioprinted / templated"
    if is_membrane:
        return "Membrane- or channel-based barrier interface"
    return UNRESOLVED


# ---------------------------------------------------------------------------
# 4. Perfusion type: in vitro / in vivo / both
# ---------------------------------------------------------------------------
def classify_perfusion_type(vascular_architecture_assessment: str, screening_notes: str) -> str:
    text = _strip_boilerplate(_norm(vascular_architecture_assessment, screening_notes))
    if not text.strip():
        return UNRESOLVED

    in_vivo_markers = [
        "host anastomosis", "in vivo host", "mouse implantation", "after transplantation",
        "host-connected perfusion", "in vivo perfusion", "implanted into mice", "host vasculature",
    ]
    in_vitro_markers = [
        "flow: yes", "chip perfusion", "continuous perfusion", "pump-driven", "gravity-driven",
        "bioreactor", "inlet-outlet", "inlet/outlet", "luminal flow", "perfusable", "pump/tracer",
        "in vitro perfusion", "in vitro chip circulation",
    ]
    static_markers = ["static", "no flow", "flow: no", "not perfused"]

    is_in_vivo = any(m in text for m in in_vivo_markers)
    is_in_vitro = any(m in text for m in in_vitro_markers)
    is_static = any(m in text for m in static_markers)

    if is_in_vivo and is_in_vitro:
        return "Both (in vitro + in vivo)"
    if is_in_vivo:
        return "In vivo only (host-anastomosis; not NAM-relevant)"
    if is_in_vitro:
        return "In vitro only"
    if is_static:
        return "Static / no perfusion demonstrated"
    return UNRESOLVED


# ---------------------------------------------------------------------------
# 5. ECM / matrix material(s) used for seeding — multi-label
# ---------------------------------------------------------------------------
_ECM_VOCAB = {
    "Collagen I": ["collagen i", "collagen type i", "collagen-i", "col i", "collagen1"],
    "Collagen IV": ["collagen iv", "collagen type iv"],
    "Fibrin": ["fibrin"],
    "Matrigel": ["matrigel"],
    "Laminin": ["laminin"],
    "Entactin": ["entactin"],
    "Gelatin / GelMA": ["gelatin", "gelma"],
    "Fibronectin": ["fibronectin"],
    "Hyaluronic acid": ["hyaluronic", "hyaluronan", "methacrylated ha", "hama"],
    "Alginate": ["alginate"],
    "Decellularized ECM": ["decellularized", "decell ecm", "decm"],
    "Silk": ["silk fibroin", "silk scaffold", "silk "],
    "PEG-based hydrogel": ["polyethylene glycol", "peg hydrogel", "peg-based", "peg mmp", "peg "],
    "Basement membrane extract": ["basement membrane extract", "bme "],
    "Lectin-coated surface": ["lectin"],
    "Bioink / printing support material": ["bioink", "xanthan"],
    "Synthetic membrane (non-biological)": [
        "silicon membrane", "silicon nitride", "polycarbonate membrane", "pet membrane",
    ],
    "Engineered / unspecified ECM": ["engineered ecm", "ecm layer", "extracellular matrix layer"],
}

# "Collagen (type unspecified)" is a controlled-vocab member too, but it's
# intentionally NOT matched here: "collagen" is a substring of "collagen i"/
# "collagen iv", so adding a bare "collagen" keyword would double-match
# against those more specific entries. It's currently only ever assigned via
# the manual axis_review override columns (outputs/literature_master.csv),
# where a human reviewer confirmed the source only says "collagen" without
# specifying type I/IV (e.g. P002, P005-P007, P013, P019) — see
# `load_graph.py`'s override handling.

# Substring (not exact-match) check: this corpus phrases "not reported" many
# different ways ("Not reported in reviewed evidence", "Not reported in
# abstract unless specified in summary", etc.).
_ECM_UNRESOLVED_SUBSTRINGS = [
    "not reported", "not extracted", "not established", "detailed recipe not reproduced",
]
_ECM_UNRESOLVED_EXACT = {"", "n/a", "none"}


def classify_ecm_materials(matrix_raw: str) -> list[str]:
    """Return a list of one or more normalized ECM/matrix material names."""
    text = (matrix_raw or "").strip().lower()
    if text in _ECM_UNRESOLVED_EXACT or any(m in text for m in _ECM_UNRESOLVED_SUBSTRINGS):
        return ["Not reported"]

    found = [name for name, keywords in _ECM_VOCAB.items() if any(k in text for k in keywords)]
    if not found:
        return ["Other / unspecified"]
    return found
