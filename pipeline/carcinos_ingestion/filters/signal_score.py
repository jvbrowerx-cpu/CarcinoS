"""
Deterministic signal scoring — ADMIT-ONLY architecture (v3).

CarcinoS philosophy: an empty week is better than a weak card.

A paper may proceed to Pass 2 ONLY if it carries a QUALIFYING SIGNAL.
The LLM cannot override the absence of a qualifying signal.

Architecture (three gates):

  Gate 1  Hard always-reject (narrow by design)
          Only two categories where Gate 2 would genuinely false-positive:
            1. Statistical re-analyses (mixture cure model, reconstructed IPD)
               — reference trial names/endpoints and would fool QS_WATCHED_TRIAL
            2. Narrative/scoping/literature reviews — can match guideline
               language and incorrectly fire QS_GUIDELINE
          Everything else (surgical comparisons, retrospective series, palliative
          intent studies) passes to Gate 2. Pass 2 handles quality decisions.

  Gate 2  QUALIFYING SIGNAL (admit-only gate)
          One of eleven positive signals required (checked in priority order):

            FDA                    — approval, label change, accelerated
                                     approval, or market withdrawal
            GUIDELINE              — NCCN / ASCO / ESMO / ASTRO / ASH
                                     guideline update or revision
            WATCHED_TRIAL          — named trial on the site's curated watchlist;
                                     auto-admits regardless of other signals so
                                     major ongoing trials are never missed
            NEGATIVE_TRIAL         — randomized trial that explicitly failed its
                                     primary endpoint; practice-changing by
                                     establishing what NOT to do (Tier B/C)
            PHASE_III_RANDOMIZED   — primary results of a phase III RCT
            RANDOMIZED_DEESCALATION — randomized noninferiority or
                                     de-escalation trial with clinical endpoint
            PHASE_II_RANDOMIZED    — any randomized phase II trial in any
                                     cancer type (common cancers included);
                                     Pass 2 routinely assigns Incremental
            MAJOR_CONFERENCE       — LBA / plenary at ASCO, ESMO, ASTRO,
                                     ASH, AACR, SITC, SABCS, ESGO
            DIRECT_RADONC_TRIAL    — prospective trial directly changing
                                     RT dose, field, fractionation, or sequencing
            REGULATORY_PHASE_II    — phase II explicitly linked to regulatory
                                     action or new orphan-disease standard
            META_ANALYSIS          — meta-analysis or systematic review;
                                     Pass 2 assigns Incremental or Horizon
                                     based on topic and data quality
            TOP_JOURNAL            — published in a Tier 1 oncology journal
                                     AND contains a clinical/outcome signal;
                                     journal alone is not sufficient — requires
                                     trial or outcome language to prevent dilution

          If qualifying_signal == NONE → rejected before any LLM call.

  Gate 3  Additive scoring
          Determines priority ranking. Score does NOT affect eligibility.

Design rationale (v3 changes):
  • Meta-analyses removed from hard excludes. A landmark IPD meta-analysis
    or a practice-confirming pooled analysis in NEJM or Lancet Oncology
    belongs on the radar. Pass 2 will set reject_recommendation=true for
    low-value reviews.
  • QS_PHASE_II_RANDOMIZED added so any randomized Phase II reaches Pass 2.
    The LLM tier mapping is calibrated to assign Incremental (Tier B) to
    adequately powered Phase II randomized trials with significant endpoints.
  • QS_TOP_JOURNAL restores coverage of JAMA, Lancet, IJROBP, JCO, etc.
    after the journal force-keep was removed in v2.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from ..normalize.canonical import CanonicalCandidate


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOP_N_PER_SITE = 6    # max per site forwarded to LLM (10 sites × 6 = 60 max)
                       # Pass 2 filters ~60% to NOISE → ~25 survivors
                       # Strict tier mapping then cuts to target 10-15 cards/week

# Qualifying signal codes
QS_FDA                     = "FDA"
QS_GUIDELINE               = "GUIDELINE"
QS_WATCHED_TRIAL           = "WATCHED_TRIAL"          # named trial on site watchlist
QS_NEGATIVE_TRIAL          = "NEGATIVE_TRIAL"         # randomized trial that failed primary endpoint
QS_PHASE_III_RANDOMIZED    = "PHASE_III_RANDOMIZED"
QS_RANDOMIZED_DEESCALATION = "RANDOMIZED_DEESCALATION"
QS_PHASE_II_RANDOMIZED     = "PHASE_II_RANDOMIZED"   # any randomized Ph II
QS_MAJOR_CONFERENCE        = "MAJOR_CONFERENCE"
QS_DIRECT_RADONC_TRIAL     = "DIRECT_RADONC_TRIAL"
QS_REGULATORY_PHASE_II     = "REGULATORY_PHASE_II"
QS_META_ANALYSIS           = "META_ANALYSIS"          # meta-analysis / SR
QS_TOP_JOURNAL             = "TOP_JOURNAL"             # Tier 1 journal + clinical signal
QS_FORCE_KEEP              = "FORCE_KEEP"              # FDA records
QS_LLM_CURATED             = "LLM_CURATED"            # Lane 5 web search (pre-filtered by LLM)
QS_NONE                    = "NONE"

QUALIFYING_SIGNALS = frozenset({
    QS_FDA, QS_GUIDELINE, QS_WATCHED_TRIAL, QS_NEGATIVE_TRIAL,
    QS_PHASE_III_RANDOMIZED, QS_RANDOMIZED_DEESCALATION, QS_PHASE_II_RANDOMIZED,
    QS_MAJOR_CONFERENCE, QS_DIRECT_RADONC_TRIAL, QS_REGULATORY_PHASE_II,
    QS_META_ANALYSIS, QS_TOP_JOURNAL, QS_FORCE_KEEP, QS_LLM_CURATED,
})

# ---------------------------------------------------------------------------
# Base scores — signal-centric scoring (module-level for inspection/testing)
#
# The unit of output is an OncologySignal, not a paper. Scores reflect the
# clinical importance of the SIGNAL TYPE, not the prestige of the source.
#
# Hard invariants:
#   FDA approval MUST always outrank any paper.
#   Guideline update MUST always outrank a Phase III paper.
#   A Phase III positive MUST outrank a conference abstract.
#   A low-impact paper MUST NEVER outrank an FDA approval or guideline update.
#   (Additive bonuses max ~35 pts — never enough to flip these orderings.)
# ---------------------------------------------------------------------------

QS_BASE: dict[str, int] = {
    QS_FDA:                     100,  # FDA approval / label change / accelerated approval
    QS_FORCE_KEEP:              100,  # FDA records pre-qualified at source
    QS_GUIDELINE:                90,  # NCCN/ASCO/ESMO/ASTRO formal guideline revision
    QS_PHASE_III_RANDOMIZED:     85,  # Positive Phase III RCT primary results
    QS_WATCHED_TRIAL:            85,  # Named major trial on watchlist (same tier as Ph III)
    QS_NEGATIVE_TRIAL:           80,  # Negative Phase III — changes expectations
    QS_MAJOR_CONFERENCE:         75,  # ASCO/ESMO/ASTRO plenary or LBA
    QS_RANDOMIZED_DEESCALATION:  75,  # Randomized noninferiority/de-escalation
    QS_PHASE_II_RANDOMIZED:      65,  # Biomarker-directed Phase II in high-need space
    QS_DIRECT_RADONC_TRIAL:      65,  # RadOnc dose/field/fractionation trial
    QS_REGULATORY_PHASE_II:      50,  # Phase II with regulatory link or rare disease standard
    QS_META_ANALYSIS:            40,  # Incremental: meta-analysis or systematic review
    QS_TOP_JOURNAL:              40,  # Incremental: top-journal + clinical signal
    QS_LLM_CURATED:             55,  # Lane 5 web search pre-filtered by LLM for Phase II/III/FDA
}

# Admin-visible rejection reasons (written to log; surfaced in admin portal later)
REJ_NO_SIGNAL        = "no_qualifying_signal"
REJ_REVIEW           = "review_meta_analysis"
REJ_RETROSPECTIVE    = "retrospective_database"
REJ_PRECLINICAL      = "preclinical"
REJ_PROGNOSTIC       = "prognostic_only"
REJ_SURGICAL_TECH    = "surgical_technical"
REJ_EXPLORATORY      = "exploratory_modeling"


# ---------------------------------------------------------------------------
# Gate 1: Hard always-reject (narrow)
#
# These patterns are NEVER practice-changing even when they appear alongside
# qualifying-signal language from referenced trials.  Only include patterns
# where the risk of a false positive qualifying-signal detection is real.
# ---------------------------------------------------------------------------

# Full-text hard excludes: only patterns that are structurally impossible to
# be practice-changing regardless of journal, context, or results.
_HARD_EXCLUDE_RE = re.compile(
    r"\b("
    # Statistical re-analyses of trial data — mention trial names and endpoints,
    # so they would fool QS_WATCHED_TRIAL and QS_PHASE_III. Never practice-changing.
    r"mixture cure model"
    r"|reconstructed.{0,12}(IPD|individual patient data)"
    # Narrative / scoping / literature reviews — not systematic reviews.
    # Can match guideline language and incorrectly fire QS_GUIDELINE.
    r"|narrative review|literature review|scoping review"
    r")\b",
    re.IGNORECASE,
)

# Title-only hard excludes: kept minimal — Gate 2 admit-only handles most
# post-hoc and retrospective patterns. Only exclude where Gate 2 would
# genuinely false-positive (e.g. a post-hoc of a watched trial).
_HARD_EXCLUDE_TITLE_ONLY_RE = re.compile(
    r"\b("
    r"post.hoc analysis"
    r"|(reanalysis|re-analysis).{0,30}(phase (ii|iii|2|3)|trial|study)"
    r"|(secondary analysis).{0,30}(phase (ii|iii|2|3)|trial data)"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Gate 2: Qualifying signal detectors
#
# Each function returns True if its qualifying signal is present.
# Checked in priority order; the first True match wins.
# ---------------------------------------------------------------------------

# ── 1. FDA ───────────────────────────────────────────────────────────────────

_FDA_RE = re.compile(
    r"("
    r"fda.{0,5}(approv|granted|cleared|authorized)"
    r"|fda.{0,10}(label|labeling).{0,15}(update|change|revision)"
    r"|accelerated approval"
    r"|full approval|regular approval"
    r"|fda.{0,10}withdrawal|market withdrawal"
    r"|(approv|granted).{0,30}(nda|bla|snda|sbla)\b"
    r"|\b(nda|bla|snda|sbla).{0,30}approv"
    r")",
    re.IGNORECASE,
)

def _is_fda(text: str, pub_types: list[str], conference_source: str) -> bool:
    if conference_source == "FDA":
        return True
    if any("fda drug approval" in pt.lower() for pt in pub_types):
        return True
    return bool(_FDA_RE.search(text))


# ── 2. Guideline update ───────────────────────────────────────────────────────

_GUIDELINE_BODY_RE = re.compile(
    r"\b(nccn|asco|esmo|astro|ash|esgo|eortc|aua|nci|who)\b",
    re.IGNORECASE,
)
_GUIDELINE_EVENT_RE = re.compile(
    r"\b("
    r"guideline.{0,20}(update|change|revision|incorporat|now recommend)"
    r"|updated.{0,15}guideline"
    r"|new.{0,10}guideline"
    r"|consensus.{0,15}(update|recommendation|statement)"
    r"|practice.{0,10}guideline"
    r"|clinical practice.{0,10}(update|guideline)"
    r")\b",
    re.IGNORECASE,
)

def _is_guideline(text: str) -> bool:
    # Must name a guideline body AND describe an update/change event
    return bool(_GUIDELINE_BODY_RE.search(text) and _GUIDELINE_EVENT_RE.search(text))


# ── 3. Phase III RCT (primary results) ────────────────────────────────────────

_PHASE3_RE = re.compile(r"\bphase.?(iii|3)\b", re.IGNORECASE)
_RANDOMIZED_RE = re.compile(
    r"\b(randomized|randomised|rct|randomly (assigned|allocated|administered)|random assignment)\b",
    re.IGNORECASE,
)
# Disqualify if this paper is borrowing phase III language from a referenced trial
_PHASE3_BORROWED_RE = re.compile(
    r"\b("
    # "previously reported/published" = borrowing prior trial data (not own RCT)
    # "updated" and "revised" removed: updated OS analyses at longer follow-up ARE
    # practice-changing and should not be rejected for mentioning "updated Phase III"
    r"previously (reported|published).{0,20}(phase (iii|3)|trial)"
    r"|(based on|from).{0,20}(phase (iii|3)|trial).{0,20}(data|results|population)"
    r"|using data from.{0,30}(phase (iii|3)|trial)"
    r")\b",
    re.IGNORECASE,
)

_PHASE3_RETROSPECTIVE_RE = re.compile(
    r"\b("
    r"retrospective (analysis|study|cohort|review|series)"
    r"|(database|registry|SEER|NCDB).{0,20}(analysis|study|cohort)"
    r"|real.world (data|evidence|analysis|cohort)"
    r"|administrative data|claims data"
    r")\b",
    re.IGNORECASE,
)

def _is_phase3_rct(text: str, title: str = "") -> bool:
    if not _PHASE3_RE.search(text):
        return False
    if not _RANDOMIZED_RE.search(text):
        return False
    if _PHASE3_BORROWED_RE.search(text):
        return False
    # Retrospective studies sometimes mention "randomized" in background context.
    # Check title only — a Phase III RCT paper discussing "real-world evidence" in
    # its conclusion should not be disqualified; only title-level retrospective
    # framing indicates the study itself is retrospective.
    if _PHASE3_RETROSPECTIVE_RE.search(title):
        return False
    return True


# ── 4. Randomized de-escalation / noninferiority ──────────────────────────────

_DEESC_EVENT_RE = re.compile(
    r"\b("
    r"non.?inferiority|noninferiority"
    r"|de.escalation|deescalation"
    r"|dose reduction|dose omission|treatment omission"
    r"|omission of (chemotherapy|radiation|chemo|RT|radiotherapy|adjuvant)"
    r"|watch.and.wait|active surveillance"
    r")\b",
    re.IGNORECASE,
)

def _is_randomized_deescalation(text: str) -> bool:
    # Must be randomized AND describe a de-escalation/noninferiority intent
    return bool(_RANDOMIZED_RE.search(text) and _DEESC_EVENT_RE.search(text))


# ── 5. Major conference LBA / plenary ────────────────────────────────────────

_MAJOR_CONFERENCES = frozenset({"ASCO", "ESMO", "ASTRO", "ASH", "AACR", "SITC", "SABCS", "ESGO"})

_LBA_RE = re.compile(
    r"\b("
    r"late.breaking (abstract|trial|session|oral|data)"
    r"|plenary (session|abstract|oral|presentation)"
    r"|presidential (symposium|session)"
    r")\b",
    re.IGNORECASE,
)
_CONF_LBA_COMBINED_RE = re.compile(
    r"(asco|esmo|astro|ash|aacr|sitc|sabcs|esgo).{0,30}"
    r"(late.breaking|plenary|presidential)"
    r"|(late.breaking|plenary|presidential).{0,30}"
    r"(asco|esmo|astro|ash|aacr|sitc|sabcs|esgo)",
    re.IGNORECASE,
)

# For conference-tagged papers (conference_source set by the conference lane),
# require either LBA/plenary label OR solid trial-result language.
# ASCO abstract supplement papers are indexed in PubMed with publication type
# "Congress" but their abstract text does NOT contain "late-breaking" — that
# label is presentation-metadata, not abstract content. Without this fallback,
# ASCO LBAs tagged by the conference lane fall through to QS_NONE.
_CONF_TRIAL_SIGNAL_RE = re.compile(
    r"\b("
    r"phase (ii|iii|2|3)|randomized|randomised|rct"
    r"|overall survival|progression.free|disease.free|event.free"
    r"|hazard ratio|median (os|pfs|dfs|efs)"
    r"|primary endpoint met|primary outcome"
    r"|pivotal|practice.changing|standard of care"
    r"|fda.approv|guideline.{0,20}(update|incorporat|recommend)"
    r")\b",
    re.IGNORECASE,
)

def _is_major_conference_lba(
    text: str, pub_types: list[str], conference_source: str
) -> bool:
    cs = (conference_source or "").upper()
    if cs in _MAJOR_CONFERENCES:
        # Conference-tagged paper from the conference lane (pub type "Congress").
        # Qualify if it has an LBA/plenary label OR solid trial-result language.
        # Most ASCO LBA abstracts in PubMed lack "late-breaking" in their text —
        # the designation is meeting metadata, not in the abstract itself.
        return bool(_LBA_RE.search(text) or _CONF_TRIAL_SIGNAL_RE.search(text))
    # Non-conference-tagged paper from the main lanes that references a major LBA
    return bool(_CONF_LBA_COMBINED_RE.search(text))


# ── 6. Prospective trial directly changing RT parameters ──────────────────────

# Must be a prospective trial context (not just retrospective RT outcomes)
_PROSP_TRIAL_RE = re.compile(
    r"\b("
    r"randomized|randomised|rct"
    r"|phase (i+|[1-3]) (trial|study|rct)"
    r"|prospective (randomized|randomised|trial|study)"
    r")\b",
    re.IGNORECASE,
)
# The RT parameter being directly evaluated must be the trial's subject,
# not just background context
_DIRECT_RT_RE = re.compile(
    r"\b("
    r"dose escalation|dose de.escalation|dose reduction.{0,20}(radiation|RT|radiotherapy)"
    r"|hypofractionat|hyperfractionat|accelerated fractionat"
    r"|stereotactic (body|ablative|radiosurgery)|sbrt|sabr|srs"
    r"|elective nodal (irradiation|treatment|radiation|field)"
    r"|omission of (radiation|radiotherapy|RT|irradiation|elective)"
    r"|radiation (field|volume).{0,20}(reduc|modif|chang|narrow)"
    r"|whole.breast (irradiation|radiation)"
    r"|accelerated partial.{0,5}breast"
    r"|proton.{0,20}(versus|compared|randomized|trial)"
    r"|particle (therapy|beam).{0,20}(versus|randomized|trial)"
    r"|sequential.{0,10}versus.{0,10}concurrent.{0,20}(chemo|radiation|RT)"
    r"|total (body|marrow|lymphoid).{0,10}irradiation"
    r"|brachytherapy.{0,20}(randomized|versus|trial)"
    r"|concurrent.{0,10}(chemoradiation|chemoradiotherapy).{0,20}(versus|compared|trial)"
    r")\b",
    re.IGNORECASE,
)

def _is_direct_radonc_trial(text: str) -> bool:
    return bool(_PROSP_TRIAL_RE.search(text) and _DIRECT_RT_RE.search(text))


# ── 7. Phase II with regulatory or rare-disease standard ──────────────────────

_PHASE2_RE = re.compile(r"\bphase.?(ii|2)\b", re.IGNORECASE)
_REGULATORY_CONTEXT_RE = re.compile(
    r"\b("
    r"accelerated approval|breakthrough therapy"
    r"|orphan drug|orphan.{0,10}designation"
    r"|rare.{0,10}(cancer|tumor|tumour|malignancy|disease|histology|sarcoma)"
    r"|new standard of care|establishes.{0,10}standard"
    r"|practice.changing|practice change"
    r"|regulatory submission|nda|bla"
    r")\b",
    re.IGNORECASE,
)

def _is_regulatory_phase2(text: str) -> bool:
    return bool(_PHASE2_RE.search(text) and _REGULATORY_CONTEXT_RE.search(text))


# ── 8. Phase II randomized (any cancer, any setting) ─────────────────────────

def _is_phase2_randomized(text: str) -> bool:
    """
    Any randomized Phase II trial, regardless of cancer type.
    Phase II single-arm studies do NOT qualify here — they need
    QS_DIRECT_RADONC_TRIAL or QS_REGULATORY_PHASE_II.
    """
    return bool(_PHASE2_RE.search(text) and _RANDOMIZED_RE.search(text))


# ── 9. Meta-analysis / systematic review ────────────────────────────────────

_META_ANALYSIS_RE = re.compile(
    r"\b(meta.analysis|systematic review|pooled analysis|individual patient data meta)\b",
    re.IGNORECASE,
)

def _is_meta_analysis_or_review(text: str) -> bool:
    """
    Identify meta-analyses, systematic reviews, and pooled analyses.
    These are no longer hard-excluded; Pass 2 determines if they are
    Incremental (landmark IPD pooling, practice-confirming review) or
    Horizon (emerging signal summarized) vs. noise (settled questions).
    Narrative / scoping / literature reviews remain hard-excluded.
    """
    return bool(_META_ANALYSIS_RE.search(text))


# ── 10. Named trial on the site watchlist ────────────────────────────────────

def _is_watched_trial(title: str, abstract: str, watched_trials: frozenset[str]) -> bool:
    """
    Auto-admit any paper that names a trial from the site's curated watchlist.
    Matched title-first (lower false-positive rate), then abstract.
    Entries can be trial acronyms (e.g. "LAURA", "PATHOS") or NCT numbers
    (e.g. "NCT03521154").  Matching is case-insensitive whole-word for
    short acronyms and substring for NCT numbers.
    """
    if not watched_trials:
        return False
    # Normalize title + abstract to lowercase for matching
    t = (title or "").lower()
    a = (abstract or "").lower()
    for trial in watched_trials:
        needle = trial.lower().strip()
        if not needle:
            continue
        # NCT numbers: substring match is fine
        if needle.startswith("nct"):
            if needle in t or needle in a:
                return True
        else:
            # Acronym: require word boundary in title first, then abstract
            pattern = rf"\b{re.escape(needle)}\b"
            if re.search(pattern, t) or re.search(pattern, a):
                return True
    return False


# ── 3b. Negative trial — randomized + failed primary endpoint ─────────────────
#
# Checked BEFORE QS_PHASE_III_RANDOMIZED in priority so negative trials get their
# own signal code (not QS_PHASE_III_RANDOMIZED), allowing tier_logic.py to route
# them to Tier B (Phase III negative → practice-changing "what NOT to do") rather
# than falling through to NOISE under the standard Phase III path.
#
# Requires: randomized language (already in _RANDOMIZED_RE) AND explicit language
# about a failed or missed primary endpoint. "No significant difference" alone is
# not enough — it must reference the primary endpoint or a major survival outcome.

_NEGATIVE_TRIAL_RE = re.compile(
    r"("
    r"did not meet.{0,40}primary (endpoint|outcome)"
    r"|primary (endpoint|outcome).{0,20}(was not met|not met|not achieved|not reached)"
    r"|failed to meet.{0,30}primary (endpoint|outcome)"
    r"|missed.{0,20}(its |the )?primary (endpoint|outcome)"
    r"|failed to demonstrate.{0,40}(superiority|significant (benefit|improvement|difference))"
    r"|did not (improve|demonstrate|achieve).{0,40}(overall survival|progression.free|primary endpoint)"
    r"|no significant (difference|improvement|benefit).{0,30}(overall survival|progression.free survival|primary endpoint)"
    r"|negative (trial|study|result).{0,20}(phase (ii|iii|2|3)|randomized|randomised)"
    r"|(phase (ii|iii|2|3)|randomized|randomised).{0,30}negative (trial|study|result)"
    r"|statistically (non.significant|not significant).{0,30}(primary|os\b|overall survival|pfs)"
    r"|did not (reach|achieve).{0,30}(statistical significance|primary endpoint|os\b|pfs)"
    r")",
    re.IGNORECASE,
)

def _is_negative_trial(text: str) -> bool:
    """
    Randomized trial (Phase II or III) that explicitly reports failing its
    primary endpoint. These are practice-changing in a different direction —
    they establish what NOT to do — and must not fall through to NOISE.

    Checked before QS_PHASE_III_RANDOMIZED so negative trials get their own
    signal code, allowing tier_logic.py to route them distinctly.
    """
    return bool(_RANDOMIZED_RE.search(text) and _NEGATIVE_TRIAL_RE.search(text))


# ── 11. Top-tier oncology journal + clinical/outcome signal ───────────────────
#
# Requiring BOTH journal and a clinical signal prevents editorials, letters,
# commentaries, and methodology papers from qualifying via journal alone.
# The clinical signal is broad — any trial, endpoint, or regulatory language.

_TOP_TIER_JOURNALS: frozenset[str] = frozenset({
    # General high-impact
    "new england journal of medicine", "nejm",
    "lancet",
    "jama",
    "nature medicine",
    "nejm evidence",
    # Oncology flagship
    "lancet oncology",
    "jama oncology",
    "journal of clinical oncology", "jco",
    "annals of oncology",
    "journal of the national cancer institute", "jnci",
    "cancer cell",
    # Radiation oncology
    "international journal of radiation oncology biology physics",
    "international journal of radiation oncology, biology, physics",
    "ijrobp",
    "radiotherapy and oncology",
    "practical radiation oncology",
    # Disease site flagship
    "journal of thoracic oncology",
    "european urology",
    "gynecologic oncology",
    "blood",
    "leukemia",
    "journal of hematology and oncology",
    "clinical cancer research",
})

_TOP_JOURNAL_CLINICAL_RE = re.compile(
    r"\b("
    # Trial design
    r"randomized|randomised|phase (ii|iii|2|3)|clinical trial|rct"
    r"|noninferiority|non.inferiority|de.escalation"
    # Outcome signals
    r"|overall survival|progression.free|disease.free|event.free"
    r"|locoregional control|local control|recurrence.free"
    r"|objective response|pathologic response|complete response"
    r"|hazard ratio|median (os|pfs|dfs|efs)\b"
    # Regulatory / guideline
    r"|fda.approv|guideline|standard of care|practice.changing"
    r")\b",
    re.IGNORECASE,
)

def _journal_is_top_tier(journal: str) -> bool:
    """Check journal name alone (no clinical signal required)."""
    j = (journal or "").lower().strip()
    if not j:
        return False
    if j in _TOP_TIER_JOURNALS:
        return True
    for name in _TOP_TIER_JOURNALS:
        if len(name) >= 8 and (name in j or j in name):
            return True
    return False

def _is_top_journal(journal: str, text: str) -> bool:
    """
    Tier 1 journal AND a clinical/outcome signal in the abstract.
    Journal alone is not sufficient — prevents editorials and letters
    from qualifying as TOP_JOURNAL.
    """
    return _journal_is_top_tier(journal) and bool(_TOP_JOURNAL_CLINICAL_RE.search(text))


# ---------------------------------------------------------------------------
# Rejection reason classifier
# Called only when qualifying_signal == NONE.
# Returns the most specific reason code for admin transparency.
# ---------------------------------------------------------------------------

_REJ_PRECLINICAL_RE = re.compile(
    r"\b(in vitro|in vivo|cell line|xenograft|mouse model|murine|organoid|preclinical)\b",
    re.IGNORECASE,
)
_REJ_SURGICAL_RE = re.compile(
    r"\b("
    r"surgical (technique|approach|outcome|series)"
    r"|operative technique|endoscopic|robotic|laparoscopic"
    r"|auto.{0,5}(segmentation|contouring|delineation)"
    r"|automated (segmentation|planning|delineation)"
    r")\b",
    re.IGNORECASE,
)
_REJ_EXPLORATORY_RE = re.compile(
    r"\b("
    r"exploratory analysis|modeling study|simulation|statistical model"
    r"|decision analysis|cost.effectiveness|cost.utility|markov model"
    r")\b",
    re.IGNORECASE,
)
_REJ_REVIEW_RE = re.compile(
    r"\b(systematic review|meta.analysis|pooled analysis|literature review|scoping review)\b",
    re.IGNORECASE,
)
_REJ_RETRO_RE = re.compile(
    r"\b("
    r"retrospective|(database|registry).{0,10}(study|analysis|cohort)"
    r"|SEER|NCDB|NSQIP|EHR|electronic health record"
    r"|administrative data|claims data|real.world (data|evidence)"
    r")\b",
    re.IGNORECASE,
)
_REJ_PROGNOSTIC_RE = re.compile(
    r"\b("
    r"prognostic (factor|marker|model|score|index|nomogram|signature|biomarker)"
    r"|predictive (model|score|nomogram)"
    r")\b",
    re.IGNORECASE,
)

def _classify_rejection(text: str, title: str) -> str:
    if _REJ_PRECLINICAL_RE.search(text):  return REJ_PRECLINICAL
    if _REJ_SURGICAL_RE.search(title):    return REJ_SURGICAL_TECH
    if _REJ_EXPLORATORY_RE.search(text):  return REJ_EXPLORATORY
    if _REJ_REVIEW_RE.search(text):       return REJ_REVIEW
    if _REJ_RETRO_RE.search(text):        return REJ_RETROSPECTIVE
    if _REJ_PROGNOSTIC_RE.search(text):   return REJ_PROGNOSTIC
    return REJ_NO_SIGNAL


# ---------------------------------------------------------------------------
# Gate 3: Additive scoring
# Determines tier-priority ranking among qualifying candidates.
# Score does NOT affect eligibility (qualifying_signal governs that).
# ---------------------------------------------------------------------------

def _additive_score(
    text: str, title: str, pub_types_lower: list[str], qualifying_signal: str
) -> tuple[int, list[str]]:
    score   = 0
    signals = []

    base = QS_BASE.get(qualifying_signal, 0)
    score += base
    signals.append(f"{qualifying_signal} base +{base}")

    # ── Additive bonuses — rank within a qualifying signal tier ────────────
    #
    # IMPORTANT: Additive bonuses rank papers within the same signal tier.
    # They do NOT allow a lower-signal paper to outrank a higher-signal one.
    # Example: TOP_JOURNAL base=40 + max bonuses ~25 = 65, which is still
    # below PHASE_III_RANDOMIZED base=85 with no bonuses (85). This is
    # intentional: a top-journal retrospective can never outrank a Phase III.

    # OS benefit (+10) — most clinically meaningful endpoint
    if any(t in text for t in ("overall survival", "os benefit", "median os", "improved survival")):
        score += 10
        signals.append("OS +10")

    # Survival endpoint (PFS/EFS/DFS/MFS) (+6)
    if any(t in text for t in (
        "progression-free", "progression free",
        "event-free", "event free", "metastasis-free", "metastasis free",
        "disease-free", "disease free", "recurrence-free", "recurrence free",
    )):
        score += 6
        signals.append("Survival endpoint +6")

    # Radiation oncology direct relevance (+8)
    if any(t in text for t in (
        "radiation dose", "radiation field", "hypofractionat",
        "stereotactic", "sbrt", "sabr", "chemoradiation",
        "chemoradiotherapy", "radiotherapy", "brachytherapy",
        "elective nodal", "proton",
    )):
        score += 8
        signals.append("RT relevance +8")

    # De-escalation / noninferiority (+6)
    if any(t in text for t in ("de-escalation", "de escalation", "noninferiority", "non-inferiority")):
        score += 6
        signals.append("De-escalation +6")

    # First-line (+4) — front-line treatment changes affect the most patients
    if any(t in text for t in ("first-line", "first line", "frontline", "front-line")):
        score += 4
        signals.append("First-line +4")

    # Hard-to-treat cancer (+4)
    if any(t in text for t in ("pancreatic", "sclc", "glioblastoma", "gbm", "mesothelioma")):
        score += 4
        signals.append("Hard-to-treat cancer +4")

    # LBA / plenary (+5) — major meeting presentation confirms priority
    if any(t in text for t in ("late-breaking", "late breaking", "plenary session", "presidential symposium")):
        score += 5
        signals.append("LBA/plenary +5")

    # Exploratory / post-hoc penalty (-15)
    # Larger penalty than v2 to enforce: do NOT allow a paper to pass only
    # because it is in a prestigious journal if the result is exploratory.
    if any(t in text for t in ("subgroup analysis", "post-hoc", "post hoc", "exploratory analysis", "hypothesis-generating")):
        score -= 15
        signals.append("Exploratory -15")

    # Editorial / review penalty (-15)
    # Do NOT allow a commentary in NEJM to score above a Phase III trial.
    if any(t in pub_types_lower for t in ("editorial", "comment", "letter", "review", "news")):
        score -= 15
        signals.append("Editorial/review -15")

    # Phase III without interpretable result penalty (-10)
    # A Phase III paper that doesn't report a clinically interpretable endpoint
    # should not score as high as one that does.
    if "not_reported" in text or "not reported" in text:
        if "primary endpoint" in text:
            score -= 10
            signals.append("Uninterpretable Phase III -10")

    return max(0, score), signals


# ---------------------------------------------------------------------------
# SignalScore dataclass
# ---------------------------------------------------------------------------

@dataclass
class SignalScore:
    qualifying_signal: str        # one of QS_* constants
    score: int                    # additive score for tier-ranking
    signals: list[str] = field(default_factory=list)
    hard_excluded: bool = False
    exclusion_reason: str = ""
    rejection_reason: str = ""    # populated when qualifying_signal == NONE
    # Legacy compat fields (used by pipeline.py force-keep path)
    has_trigger: bool = True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def score_candidate(
    cand: CanonicalCandidate,
    watched_trials: frozenset[str] = frozenset(),
) -> SignalScore:
    """
    Run all three gates.  Return a SignalScore.

    Args:
        cand: Candidate paper to evaluate.
        watched_trials: Site-specific frozenset of trial names/NCT numbers
            that auto-admit regardless of other signals. Pass
            frozenset(site.watched_trials) from the pipeline.

    Pipeline checks:
      if sig.hard_excluded                       → drop, log exclusion_reason
      if sig.qualifying_signal == QS_NONE        → drop, log rejection_reason
      else                                       → forward to Pass 2 (score ranks)
    """
    title  = cand.title or ""
    abstract = cand.abstract or ""
    text   = f"{title}\n{abstract}".lower()
    title_lower = title.lower()
    pub_types_lower = [pt.lower() for pt in cand.publication_types]

    # ── Gate 1: Hard always-reject ───────────────────────────────────────────
    m = _HARD_EXCLUDE_RE.search(text)
    if m:
        return SignalScore(
            qualifying_signal=QS_NONE,
            score=0,
            hard_excluded=True,
            exclusion_reason=m.group(0).strip(),
        )
    # Title-only hard excludes (post-hoc / secondary-analysis)
    mt = _HARD_EXCLUDE_TITLE_ONLY_RE.search(title_lower)
    if mt:
        return SignalScore(
            qualifying_signal=QS_NONE,
            score=0,
            hard_excluded=True,
            exclusion_reason=mt.group(0).strip(),
        )

    # ── Gate 2: Qualifying signal (admit-only) ───────────────────────────────
    qs = QS_NONE

    # Lane 5 (web search) records were pre-filtered by an LLM instructed to
    # return ONLY Phase II/III trials, FDA approvals, and guideline updates.
    # Running keyword patterns on their short LLM-generated summaries is
    # double-gating on text that wasn't written for PubMed vocab. Treat the
    # LLM curation itself as the qualifying signal; Pass 2 decides value.
    if (cand.conference_source or "") == "WEB_SEARCH":
        qs = QS_LLM_CURATED

    # Check in priority order (highest signal strength first).
    # WATCHED_TRIAL sits after FDA/GUIDELINE but before Phase III — a named
    # trial on the watchlist is always admitted so major ongoing trials
    # are never missed regardless of how the abstract is worded.
    elif _is_fda(text, cand.publication_types, cand.conference_source or ""):
        qs = QS_FDA
    elif _is_guideline(text):
        qs = QS_GUIDELINE
    elif _is_watched_trial(title, abstract, watched_trials):
        qs = QS_WATCHED_TRIAL
    elif _is_negative_trial(text):
        qs = QS_NEGATIVE_TRIAL
    elif _is_phase3_rct(text, title_lower):
        qs = QS_PHASE_III_RANDOMIZED
    elif _is_randomized_deescalation(text):
        qs = QS_RANDOMIZED_DEESCALATION
    elif _is_phase2_randomized(text):
        qs = QS_PHASE_II_RANDOMIZED
    elif _is_major_conference_lba(text, cand.publication_types, cand.conference_source or ""):
        qs = QS_MAJOR_CONFERENCE
    elif _is_direct_radonc_trial(text):
        qs = QS_DIRECT_RADONC_TRIAL
    elif _is_regulatory_phase2(text):
        qs = QS_REGULATORY_PHASE_II
    elif _is_meta_analysis_or_review(text):
        qs = QS_META_ANALYSIS
    elif _is_top_journal(cand.journal or "", text):
        qs = QS_TOP_JOURNAL

    if qs == QS_NONE:
        return SignalScore(
            qualifying_signal=QS_NONE,
            score=0,
            hard_excluded=False,
            rejection_reason=_classify_rejection(text, title),
        )

    # ── Gate 3: Additive scoring (tier-ranking, not eligibility) ────────────
    score, signals = _additive_score(text, title, pub_types_lower, qs)

    return SignalScore(
        qualifying_signal=qs,
        score=score,
        signals=signals,
        has_trigger=True,
        hard_excluded=False,
    )
