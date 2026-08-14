"""
Signal clustering — group AlertOutput objects into OncologySignals.

Design:
  Multiple evidence sources may all describe the same oncology signal.
  Example: the NEJM paper for the ROSELLA trial, the FDA approval press
  release, and the ASCO 2026 abstract are three EvidenceSources for one
  ROSELLA OncologySignal (relacorilant in platinum-resistant ovarian cancer).

  This module runs AFTER the existing trial_dedup (which drops lower-priority
  duplicates) and produces one OncologySignal per distinct clinical event.

Clustering keys (in priority order):
  1. trial_name  — strongest key; two records with the same trial_name are
                   always the same signal regardless of disease site.
  2. (disease_site, intervention_hash) — fallback for signals without a named
                   trial. Matches signals in the same site with similar
                   intervention text (n-gram similarity ≥ 0.75).

Source priority for the primary record (determines signal_title, key_finding,
so_what, etc.):
  FDA > JOURNAL/PUBMED with full abstract > CONFERENCE_ABSTRACT > WEB_SEARCH

This module is additive — it does not drop any alerts. It wraps them in
OncologySignal objects with a consolidated EvidenceSources list, then builds
a CarcinoSCard for each signal.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from ..signal import (
    OncologySignal,
    EvidenceSource,
    CarcinoSCard,
    SignalType,
    QS_TO_SIGNAL_TYPE,
    source_type_from_candidate,
    SIGNAL_PRIORITY,
)


# ---------------------------------------------------------------------------
# Source priority for picking the "primary" record in a cluster
# ---------------------------------------------------------------------------

_SOURCE_PRIORITY = {
    "FDA":                  0,   # highest — regulatory action is ground truth
    "NCCN":                 1,
    "ASCO":                 2,
    "ESMO":                 2,
    "ASTRO":                2,
    "PUBMED":               3,
    "JOURNAL":              3,
    "CONFERENCE_ABSTRACT":  4,
    "WEB_SEARCH":           5,
    "PRESS_RELEASE":        5,
}


def _source_priority(src: EvidenceSource) -> int:
    return _SOURCE_PRIORITY.get(src.source_type, 9)


# ---------------------------------------------------------------------------
# Text normalizer and safe cluster key builder
# ---------------------------------------------------------------------------

_STRIP_RE = re.compile(r"[^a-z0-9 ]")

def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(_STRIP_RE.sub(" ", (text or "").lower()).split())


def _signal_cluster_key(alert) -> str:
    """
    Build a conservative cluster key for signals without a named trial.

    The key combines FOUR dimensions so that only truly co-incident signals
    merge — "pembro + chemo" in NSCLC first-line is a different signal from
    "pembro + chemo" in TNBC neoadjuvant:

      1. disease_site   — cancer site from the pipeline's site config
      2. setting        — clinical setting (localized, metastatic, adjuvant, etc.)
      3. intervention   — first 4 normalized tokens of the intervention arm
      4. population     — first 3 normalized tokens (biomarker, histology, line)

    4-token intervention + 3-token population is narrow enough to prevent
    accidental cross-disease merges while still catching true duplicates
    (e.g. the same trial appearing in both PubMed and a conference abstract).

    If ANY of disease_site, setting, or the intervention tokens differ, the
    signals get separate keys — they are not merged.
    """
    p2   = alert.pass2.parsed
    cand = alert.candidate

    disease  = _normalize_text(cand.cancer_site_name)
    setting  = _normalize_text(p2.get("setting") or "other")

    intervention = _normalize_text(p2.get("intervention") or cand.title or "")
    iv_tokens = intervention.split()[:4]

    population = _normalize_text(p2.get("population") or "")
    pop_tokens = population.split()[:3]

    key_str = (
        f"{disease}"
        f"|{setting}"
        f"|{' '.join(iv_tokens)}"
        f"|{' '.join(pop_tokens)}"
    )
    return hashlib.md5(key_str.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# AlertOutput → EvidenceSource conversion
# ---------------------------------------------------------------------------

def _alert_to_evidence_source(alert) -> EvidenceSource:
    """Convert an AlertOutput to an EvidenceSource."""
    cand = alert.candidate
    p2   = alert.pass2.parsed

    return EvidenceSource(
        source_type=source_type_from_candidate(cand.conference_source),
        title=cand.title or "",
        url=cand.source_url or (
            f"https://pubmed.ncbi.nlm.nih.gov/{cand.pmid}/" if cand.pmid else None
        ),
        publication_date=cand.publication_date,
        journal=cand.journal,
        trial_name=p2.get("trial_name"),
        nct_id=(cand.nct_ids[0] if cand.nct_ids else None),
        doi=cand.doi,
        pmid=cand.pmid,
    )


# ---------------------------------------------------------------------------
# Tier code → practice_impact_level mapping
# ---------------------------------------------------------------------------

_TIER_TO_IMPACT = {"A": 1, "B": 2, "C": 3, "NOISE": 3}
_TIER_TO_SHOULD_ALERT = {"A": True, "B": True, "C": False, "NOISE": False}


# ---------------------------------------------------------------------------
# Main clustering function
# ---------------------------------------------------------------------------

def cluster_into_signals(alerts: list) -> list[OncologySignal]:
    """
    Group a list of AlertOutput objects into OncologySignal objects.

    One OncologySignal is created per distinct clinical event. Multiple
    AlertOutputs that describe the same trial or the same disease+intervention
    combination are merged into one signal with multiple evidence_sources.

    Returns a list of OncologySignal objects, highest priority first
    (FDA_APPROVAL → GUIDELINE_UPDATE → PHASE_III_POSITIVE → ...).
    """
    # Group alerts by cluster key
    # Key = trial_name (if available) or (disease_site, intervention_hash)
    clusters: dict[str, list] = {}

    for alert in alerts:
        p2   = alert.pass2.parsed
        cand = alert.candidate

        trial_name = (p2.get("trial_name") or "").strip().upper()
        if trial_name and trial_name not in ("NULL", "NONE", "NOT_REPORTED", ""):
            # Named trial: strongest key. Two records with the same trial name
            # are always the same signal regardless of disease site or setting —
            # a trial can only have one name.
            key = f"trial:{trial_name}"
        else:
            # No named trial: cluster only if disease + setting + intervention
            # + population all match. This is intentionally conservative —
            # false misses are far safer than false merges.
            key = f"signal:{_signal_cluster_key(alert)}"

        clusters.setdefault(key, []).append(alert)

    # Build one OncologySignal per cluster
    signals: list[OncologySignal] = []

    for key, cluster_alerts in clusters.items():
        # Convert all alerts to EvidenceSources, sort by source priority
        sources = sorted(
            [_alert_to_evidence_source(a) for a in cluster_alerts],
            key=_source_priority,
        )

        # The highest-priority alert provides the narrative fields
        primary_alert = sorted(
            cluster_alerts,
            key=lambda a: _source_priority(_alert_to_evidence_source(a)),
        )[0]
        primary_cand = primary_alert.candidate
        primary_p2   = primary_alert.pass2.parsed
        primary_tier = primary_alert.pass2.final_tier_code

        # Determine signal_type — prefer LLM extraction, fall back to gate mapping
        llm_signal_type: SignalType = primary_p2.get("signal_type", "OTHER")
        if not llm_signal_type or llm_signal_type == "OTHER":
            # Use the qualifying signal from the best alert
            best_qs = max(
                cluster_alerts,
                key=lambda a: getattr(a.pass1, "relevance_score", 0),
            )
            qs = getattr(best_qs.pass1.parsed, "get", lambda k, d=None: d)(
                "one_line_rationale", ""
            )
            # Extract QS code from the one_line_rationale string
            # e.g. "qualifying_signal=FDA; ..."
            import re as _re
            m = _re.search(r"qualifying_signal=([A-Z_]+)", qs or "")
            gate_qs = m.group(1) if m else "NONE"
            llm_signal_type = QS_TO_SIGNAL_TYPE.get(gate_qs, "OTHER")

        # Build signal narrative
        key_finding = primary_p2.get("key_results", {}).get("effect_size", "") or ""
        if not key_finding:
            key_finding = primary_p2.get("carcinos_one_liner", "") or ""
        so_what = primary_p2.get("carcinos_one_liner", "") or ""
        limitations_flags = primary_p2.get("limitations_flags") or []
        limitations = "; ".join(limitations_flags) if limitations_flags else ""

        # Relevance scores
        rad_rel = primary_p2.get("radiation_oncology_relevance", "none")
        radonc_score = 90.0 if rad_rel == "direct" else (50.0 if rad_rel == "indirect" else 10.0)
        conf_str = primary_p2.get("confidence", "low")
        confidence_map = {"high": 1, "moderate": 2, "low": 3}
        confidence = confidence_map.get(conf_str, 2)

        # Build trial name from first source that has one
        trial_name_display = next(
            (s.trial_name for s in sources if s.trial_name), None
        )

        signal = OncologySignal(
            signal_id=str(uuid.uuid4()),
            signal_title=(
                primary_p2.get("carcinos_one_liner")
                or primary_cand.title
                or "Untitled signal"
            )[:240],
            disease_site=primary_cand.cancer_site_name,
            tumor_type=primary_p2.get("cancer_site_subtype", "") or primary_cand.cancer_site_name,
            population=primary_p2.get("population", "") or "",
            intervention=primary_p2.get("intervention", "") or "",
            comparator=primary_p2.get("comparator") or None,
            setting=_map_setting(primary_p2.get("setting", "other_or_unclear")),
            signal_type=llm_signal_type,
            evidence_sources=sources,
            practice_impact_level=_TIER_TO_IMPACT.get(primary_tier, 3),
            confidence=confidence,
            novelty_score=float(SIGNAL_PRIORITY.get(llm_signal_type, 40)),
            immediacy_score=float(SIGNAL_PRIORITY.get(llm_signal_type, 40)),
            radonc_relevance_score=radonc_score,
            medonc_relevance_score=80.0,
            surgonc_relevance_score=40.0,
            key_finding=key_finding,
            so_what=so_what,
            limitations=limitations,
            should_alert=_TIER_TO_SHOULD_ALERT.get(primary_tier, False),
            tier_code=primary_tier,
            tier_rationale=primary_alert.pass2.tier_rationale_text,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat(),
        )
        signals.append(signal)

    # Sort: practice_impact_level ASC (1=most important), then signal priority DESC
    signals.sort(
        key=lambda s: (
            s.practice_impact_level,
            -SIGNAL_PRIORITY.get(s.signal_type, 40),
        )
    )
    return signals


def signals_to_cards(signals: list[OncologySignal]) -> list[CarcinoSCard]:
    """Convert a list of OncologySignals to display-ready CarcinoSCards."""
    return [CarcinoSCard.from_signal(s) for s in signals]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_setting(setting: str) -> str:
    """Map PASS2 setting enum to OncologySignal.ClinicalSetting."""
    _MAP = {
        "screening_prevention":   "screening",
        "localized_definitive":   "localized",
        "adjuvant":               "adjuvant",
        "neoadjuvant":            "neoadjuvant",
        "recurrent_metastatic":   "metastatic",
        "maintenance":            "metastatic",
        "survivorship_supportive": "supportive",
        "diagnostic":             "localized",
        "other_or_unclear":       "localized",
    }
    return _MAP.get(setting, "localized")
