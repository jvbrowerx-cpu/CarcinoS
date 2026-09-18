"""
Core signal-centric types for CarcinoS.

Design principle: the unit of output is not a paper, abstract, FDA page, or
press release. The unit of output is an ONCOLOGY SIGNAL.

An OncologySignal is a clinically meaningful oncology development that may
affect treatment selection, tumor board discussion, patient counseling,
guideline interpretation, trial awareness, or practice standards.

Multiple evidence sources (a PubMed abstract, an FDA approval page, a
conference abstract) can all point to the same oncology signal. The pipeline
clusters them and scores the SIGNAL, not the source.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal


# ---------------------------------------------------------------------------
# Evidence source types
# ---------------------------------------------------------------------------

SourceType = Literal[
    "FDA",
    "NCCN",
    "ASCO",
    "ASTRO",
    "ESMO",
    "PUBMED",
    "JOURNAL",
    "PRESS_RELEASE",
    "CONFERENCE_ABSTRACT",
    "WEB_SEARCH",
]

SignalType = Literal[
    "FDA_APPROVAL",
    "GUIDELINE_UPDATE",
    "PHASE_III_POSITIVE",
    "PHASE_III_NEGATIVE",
    "PRACTICE_CHANGING_PHASE_II",
    "LATE_BREAKING_ABSTRACT",
    "SAFETY_SIGNAL",
    "BIOMARKER_SIGNAL",
    "RADONC_TECHNIQUE",
    "DE_ESCALATION",
    "OTHER",
]

ClinicalSetting = Literal[
    "localized",
    "locally_advanced",
    "metastatic",
    "adjuvant",
    "neoadjuvant",
    "recurrent",
    "screening",
    "supportive",
    "other",
]

TierCode = Literal["A", "B", "C", "NOISE"]

# ---------------------------------------------------------------------------
# Confidence source — provenance of how a candidate entered the pipeline
# ---------------------------------------------------------------------------
# Set deterministically at retrieval / normalization time on CanonicalCandidate.
# NOT inferred by the LLM in Pass 2.
#
# Downstream rules (tier_logic.py, trial_dedup.py) use this to:
#   - Block weak sources (trade_press, llm_discovery) from generating cards
#     unless confirmed by a stronger source for the same trial/signal
#   - Select the highest-trust source when clustering multiple evidence
#     sources for the same trial (replaces the implicit FDA > journal >
#     conference ordering in trial_dedup.py)
#   - Provide transparent provenance metadata on every digest card

ConfidenceSource = Literal[
    "fda",                    # Lane 4: FDA oncology approval notifications page
    "guideline",              # Formal NCCN/ASCO/ESMO/ASTRO guideline record
    "peer_reviewed",          # Lanes 1/2: PubMed-indexed journal article
    "late_breaking_abstract", # Lane 3: MAJOR_CONFERENCE_HIGH (LBA/plenary/Phase III)
    "company_press_release",  # Lane 6 primary: pharma/biotech press release feed
    "trade_press",            # Lane 6 secondary: STAT/Healio/OncLive/MedPage
    "llm_discovery",          # Lane 5: GPT-4o web search, no primary source citation
]

# Higher rank = higher trust. When the same trial appears via multiple lanes,
# trial_dedup.py keeps whichever candidate has the highest rank.
# This replaces the implicit "FDA > journal > conference abstract" string
# comparison in the old deduplication logic.
CONFIDENCE_SOURCE_RANK: dict[str, int] = {
    "fda":                    100,
    "guideline":               90,
    "peer_reviewed":           80,
    "late_breaking_abstract":  70,
    "company_press_release":   40,
    "trade_press":             30,
    "llm_discovery":           20,
}

# Sources that cannot produce a digest card on their own.
# Items with these sources are routed to the trial watchlist only and are
# hard-blocked from Pass 2 unless a higher-ranked source also covers the
# same trial/signal in the same run.
DISCOVERY_ONLY_SOURCES: frozenset[str] = frozenset({
    "trade_press",
    "llm_discovery",
})


@dataclass
class EvidenceSource:
    """
    A single document that contributes to an OncologySignal.

    Multiple EvidenceSources can support one signal — e.g. the NEJM paper
    describing the ROSELLA trial, the FDA approval press release for
    relacorilant, and the ASCO abstract are three EvidenceSources for one
    ROSELLA OncologySignal.
    """
    source_type: SourceType
    title: str
    url: Optional[str] = None
    publication_date: Optional[str] = None
    journal: Optional[str] = None
    trial_name: Optional[str] = None
    nct_id: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Signal priority scoring constants
# ---------------------------------------------------------------------------

SIGNAL_PRIORITY: dict[SignalType, int] = {
    "FDA_APPROVAL":               100,
    "GUIDELINE_UPDATE":            90,
    "PHASE_III_POSITIVE":          85,
    "PHASE_III_NEGATIVE":          80,
    "LATE_BREAKING_ABSTRACT":      75,
    "PRACTICE_CHANGING_PHASE_II":  65,
    "BIOMARKER_SIGNAL":            65,
    "RADONC_TECHNIQUE":            50,
    "DE_ESCALATION":               50,
    "SAFETY_SIGNAL":               50,
    "OTHER":                       40,
}


# ---------------------------------------------------------------------------
# OncologySignal — the core pipeline output object
# ---------------------------------------------------------------------------

@dataclass
class OncologySignal:
    """
    The atomic unit of CarcinoS output.

    One signal may aggregate multiple evidence sources (PubMed paper, FDA
    approval, conference abstract) that all describe the same clinical
    development. Scoring, tier assignment, and card generation are all
    performed at the signal level, not the source level.
    """
    # Identity
    signal_id: str                        # uuid or deterministic hash
    signal_title: str                     # human-readable signal title

    # Clinical context
    disease_site: str
    tumor_type: str
    population: str
    intervention: str
    comparator: Optional[str]
    setting: ClinicalSetting

    # Classification
    signal_type: SignalType
    evidence_sources: list[EvidenceSource] = field(default_factory=list)

    # Scoring (higher = more important)
    practice_impact_level: int = 2        # 1=Practice Impacting, 2=Incremental, 3=Horizon
    confidence: int = 2                   # 1=high, 2=moderate, 3=low
    novelty_score: float = 0.0            # 0–100
    immediacy_score: float = 0.0          # 0–100; how urgently clinicians need this
    radonc_relevance_score: float = 0.0   # 0–100
    medonc_relevance_score: float = 0.0   # 0–100
    surgonc_relevance_score: float = 0.0  # 0–100

    # Narrative
    key_finding: str = ""
    so_what: str = ""
    limitations: str = ""

    # Disposition
    should_alert: bool = False
    tier_code: TierCode = "NOISE"
    tier_rationale: str = ""

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    def signal_priority(self) -> int:
        """Return the canonical priority score for this signal type."""
        return SIGNAL_PRIORITY.get(self.signal_type, 40)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# CarcinoSCard — display-ready output card
# ---------------------------------------------------------------------------

@dataclass
class CarcinoSCard:
    """
    Display-ready output card, one per OncologySignal.

    This is what gets rendered in the admin portal, digest email, and
    weekly summary. It maps directly from OncologySignal fields.
    """
    title: str
    disease_site: str
    date: str
    source_summary: str            # e.g. "NEJM + FDA approval + ASCO 2026 Plenary"
    population: str
    intervention: str
    key_finding: str
    so_what: str
    signal_strength: int           # 1=Practice Impacting, 2=Incremental, 3=Horizon
    alert_level: Literal["practice-changing", "incremental", "horizon"]
    evidence_links: list[EvidenceSource] = field(default_factory=list)

    # Optional metadata for display
    signal_type: Optional[SignalType] = None
    trial_name: Optional[str] = None
    limitations: Optional[str] = None
    radonc_relevance: Optional[str] = None    # "direct" | "indirect" | "none"
    who_should_care: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_signal(cls, signal: OncologySignal) -> "CarcinoSCard":
        """Build a display card from an OncologySignal."""
        tier_to_alert = {1: "practice-changing", 2: "incremental", 3: "horizon"}
        alert_level = tier_to_alert.get(signal.practice_impact_level, "horizon")

        # Build source summary from evidence sources
        parts: list[str] = []
        for src in signal.evidence_sources:
            if src.source_type == "FDA":
                parts.append("FDA approval")
            elif src.source_type in ("ASCO", "ESMO", "ASTRO", "ASH"):
                parts.append(f"{src.source_type} abstract")
            elif src.journal:
                parts.append(src.journal)
            else:
                parts.append(src.source_type)
        source_summary = " + ".join(parts[:3]) if parts else "CarcinoS"

        # Trial name from first source that has one
        trial_name = next(
            (s.trial_name for s in signal.evidence_sources if s.trial_name),
            None,
        )

        return cls(
            title=signal.signal_title,
            disease_site=signal.disease_site,
            date=signal.created_at[:10] if signal.created_at else "",
            source_summary=source_summary,
            population=signal.population,
            intervention=signal.intervention,
            key_finding=signal.key_finding,
            so_what=signal.so_what,
            signal_strength=signal.practice_impact_level,
            alert_level=alert_level,
            evidence_links=list(signal.evidence_sources),
            signal_type=signal.signal_type,
            trial_name=trial_name,
            limitations=signal.limitations or None,
        )


# ---------------------------------------------------------------------------
# Helpers: map pipeline output to signal types
# ---------------------------------------------------------------------------

# Map qualifying signal codes → default SignalType
# Used by signal_cluster.py to set a baseline signal_type when the LLM
# hasn't extracted one yet.
QS_TO_SIGNAL_TYPE: dict[str, SignalType] = {
    "FDA":                     "FDA_APPROVAL",
    "GUIDELINE":               "GUIDELINE_UPDATE",
    "PHASE_III_RANDOMIZED":    "PHASE_III_POSITIVE",    # direction refined by LLM
    "NEGATIVE_TRIAL":          "PHASE_III_NEGATIVE",
    "RANDOMIZED_DEESCALATION": "DE_ESCALATION",
    "MAJOR_CONFERENCE_HIGH":   "LATE_BREAKING_ABSTRACT",
    "MAJOR_CONFERENCE_LOW":    "OTHER",          # discovery only — not a card candidate
    "MAJOR_CONFERENCE":        "LATE_BREAKING_ABSTRACT",  # legacy key, kept for compat
    "DIRECT_RADONC_TRIAL":     "RADONC_TECHNIQUE",
    "PHASE_II_RANDOMIZED":     "PRACTICE_CHANGING_PHASE_II",
    "REGULATORY_PHASE_II":     "PRACTICE_CHANGING_PHASE_II",
    "WATCHED_TRIAL":           "PHASE_III_POSITIVE",    # refinement left to LLM
    "META_ANALYSIS":           "OTHER",
    "TOP_JOURNAL":             "OTHER",
    "FORCE_KEEP":              "OTHER",
    "LLM_CURATED":             "OTHER",   # signal_type refined by Pass 2
    "NONE":                    "OTHER",
}


def source_type_from_candidate(conf_source: Optional[str]) -> SourceType:
    """Map a conference_source tag to an EvidenceSource.source_type."""
    if not conf_source:
        return "PUBMED"
    cs = conf_source.upper()
    if cs == "FDA":
        return "FDA"
    if cs in ("ASCO", "ESMO", "ASTRO", "ASH", "AACR", "SABCS", "SITC", "ESGO"):
        return "CONFERENCE_ABSTRACT"
    if cs == "WEB_SEARCH":
        return "WEB_SEARCH"
    return "JOURNAL"
