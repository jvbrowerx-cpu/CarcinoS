"""
Deterministic tier assignment for CarcinoS.

This module converts structured Pass 2 LLM output into a final tier code.
The LLM extracts facts; this code converts them to a tier.
No LLM call is made here. All logic is auditable and testable.

Tier definitions
----------------
Tier A — Practice Impacting
  A practicing oncologist would change an active clinical decision because
  of this finding. Includes FDA approvals, guideline updates, and Phase III
  trials that met their primary OS endpoint.

Tier B — Incremental
  Important to know; shifts awareness or future sequencing decisions but
  does not force an immediate change. Includes Phase III PFS benefit,
  Phase II randomized, de-escalation trials, and minor guideline updates.

Tier C — Horizon
  Biologically or clinically interesting, not immediately practice-changing.
  Includes Phase II single-arm, observational/registry, biomarker signals,
  and Phase I results with remarkable early efficacy.

NOISE
  Should not appear in the digest. Includes items where:
    - clinical_actionability == "inert" and tier would be B or C
    - reject_recommendation=True with low actionability
    - confidence_source is a discovery-only source (trade_press, llm_discovery)
    - No tier rule matched

Tier A override rules
  Tier A is never downgraded by clinical_actionability (advisory only).
  FDA approvals, Phase III OS results, and formal guideline updates are
  actionable by definition — no LLM judgment should veto them.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

from ..signal import CONFIDENCE_SOURCE_RANK, DISCOVERY_ONLY_SOURCES

log = logging.getLogger("carcinos.tier_logic")


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class TierResult:
    tier: str                         # "A" | "B" | "C" | "NOISE"
    rationale: str                    # Human-readable reason for the assignment
    evidence_strength: str            # Pass-through from Pass 2: "A"|"B"|"C"|"D"
    notify: bool                      # True for Tier A; False for B/C/NOISE
    actionability_advisory: str       # clinical_actionability value (logged, not vetoing for A)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def assign_tier(
    pass2: dict,
    *,
    confidence_source: str = "peer_reviewed",
    force_keep_reason: Optional[str] = None,
) -> TierResult:
    """
    Assign a final tier to a Pass 2 result.

    Args:
        pass2:             The parsed JSON dict from Pass 2 structured output.
        confidence_source: The ConfidenceSource assigned to this candidate at
                           normalization time (from CanonicalCandidate).
        force_keep_reason: Non-None if the candidate was force-kept due to
                           top-journal override (passed guardrail check).

    Returns:
        TierResult with final tier, rationale, and metadata.
    """
    study_phase           = pass2.get("study_phase", "other_or_unclear")
    signal_type           = pass2.get("signal_type", "OTHER")
    primary_endpoint_type = pass2.get("primary_endpoint_type", "not_reported")
    primary_endpoint_met  = bool(pass2.get("primary_endpoint_met", False))
    effect_direction      = pass2.get("effect_direction", "not_reported")
    p_value_significant   = bool(pass2.get("p_value_significant", False))
    hard_to_treat         = bool(pass2.get("hard_to_treat", False))
    elevates              = bool(pass2.get("elevates_to_practice_changing", False))
    reject_rec            = bool(pass2.get("reject_recommendation", False))
    evidence_strength     = pass2.get("evidence_strength", "D")
    actionability         = pass2.get("clinical_actionability", "background")

    # ── Step 1: Block discovery-only sources ──────────────────────────────────
    # trade_press and llm_discovery cannot generate digest cards on their own.
    # Pipeline routing normally blocks them before Pass 2; this is belt-and-
    # suspenders in case a candidate slips through.
    if confidence_source in DISCOVERY_ONLY_SOURCES:
        return TierResult(
            tier="NOISE",
            rationale=(
                f"discovery_only_source: confidence_source={confidence_source!r} "
                f"cannot generate a card without confirmation from a peer-reviewed "
                f"or FDA source. Route to trial watchlist."
            ),
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # ── Step 2: Tier A — Practice Impacting ───────────────────────────────────
    # clinical_actionability is ADVISORY ONLY for Tier A items.
    # These are actionable by definition; no LLM judgment should veto them.

    # 2a. FDA approval
    if study_phase == "fda_approval" or signal_type == "FDA_APPROVAL":
        return TierResult(
            tier="A",
            rationale="fda_approval",
            evidence_strength=evidence_strength,
            notify=True,
            actionability_advisory=actionability,
        )

    # 2b. Formal guideline update
    if study_phase == "guideline_update" or signal_type == "GUIDELINE_UPDATE":
        return TierResult(
            tier="A",
            rationale="guideline_update",
            evidence_strength=evidence_strength,
            notify=True,
            actionability_advisory=actionability,
        )

    # 2c. Phase III RCT: OS primary endpoint met
    if (
        study_phase == "phase3_rct"
        and primary_endpoint_met
        and primary_endpoint_type == "overall_survival"
        and effect_direction in ("positive", "non_inferior")
        and p_value_significant
    ):
        return TierResult(
            tier="A",
            rationale=f"phase3_os_met (direction={effect_direction})",
            evidence_strength=evidence_strength,
            notify=True,
            actionability_advisory=actionability,
        )

    # 2d. Negative/safety that actively reverses clinical practice
    if elevates and signal_type in ("PHASE_III_NEGATIVE", "SAFETY_SIGNAL"):
        return TierResult(
            tier="A",
            rationale=f"elevates_to_practice_changing: {signal_type}",
            evidence_strength=evidence_strength,
            notify=True,
            actionability_advisory=actionability,
        )

    # ── Step 3: NOISE gates — apply before Tier B/C assignment ───────────────

    # 3a. reject_recommendation + low actionability → NOISE
    if reject_rec and actionability in ("background", "inert"):
        return TierResult(
            tier="NOISE",
            rationale=f"reject_recommendation=True, actionability={actionability!r}",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 3b. clinical_actionability == "inert" → NOISE for Tier B/C
    # Tier A never reaches this step (returned above).
    if actionability == "inert":
        return TierResult(
            tier="NOISE",
            rationale=(
                f"clinical_actionability=inert: no plausible impact for "
                f"{study_phase}/{signal_type}"
            ),
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # ── Step 4: Tier B — Incremental ─────────────────────────────────────────

    # 4a. Phase III: any primary endpoint met (non-OS already excluded from Tier A)
    if (
        study_phase == "phase3_rct"
        and primary_endpoint_met
        and p_value_significant
        and effect_direction in ("positive", "non_inferior")
    ):
        return TierResult(
            tier="B",
            rationale=f"phase3_{primary_endpoint_type}_met",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 4b. Phase III negative (non-elevating) — still worth knowing
    if study_phase == "phase3_rct" and signal_type == "PHASE_III_NEGATIVE":
        return TierResult(
            tier="B",
            rationale="phase3_negative_non_elevating",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 4c. Randomized Phase II with endpoint met
    if study_phase == "phase2_rct" and primary_endpoint_met:
        return TierResult(
            tier="B",
            rationale="phase2_rct_met",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 4d. De-escalation / non-inferiority confirmed
    if signal_type == "DE_ESCALATION" and effect_direction == "non_inferior":
        return TierResult(
            tier="B",
            rationale="de_escalation_confirmed",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 4e. Practice-changing Phase II (regulatory signal or high-need disease)
    if signal_type == "PRACTICE_CHANGING_PHASE_II":
        return TierResult(
            tier="B",
            rationale="practice_changing_phase2",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 4f. Late-breaking abstract with actionable signal
    if signal_type == "LATE_BREAKING_ABSTRACT" and actionability in (
        "practice_change", "awareness"
    ):
        return TierResult(
            tier="B",
            rationale="late_breaking_abstract_actionable",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # ── Step 5: Tier C — Horizon ──────────────────────────────────────────────

    # 5a. Hard-to-treat disease: any positive signal qualifies
    if hard_to_treat and actionability in ("practice_change", "awareness", "background"):
        return TierResult(
            tier="C",
            rationale=f"hard_to_treat: {study_phase}/{signal_type}",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 5b. Phase II single-arm with awareness or better
    if study_phase == "phase2_single_arm" and actionability in (
        "practice_change", "awareness"
    ):
        return TierResult(
            tier="C",
            rationale="phase2_single_arm_awareness",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 5c. Biomarker signal with direct treatment-selection implication
    if signal_type == "BIOMARKER_SIGNAL" and actionability in (
        "practice_change", "awareness"
    ):
        return TierResult(
            tier="C",
            rationale="biomarker_signal_awareness",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 5d. Radiation oncology technique with any positive signal
    if signal_type == "RADONC_TECHNIQUE" and effect_direction in (
        "positive", "non_inferior"
    ):
        return TierResult(
            tier="C",
            rationale="radonc_technique_positive",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 5e. Meta-analysis / systematic review with awareness or better
    if study_phase in ("meta_analysis", "systematic_review") and actionability in (
        "practice_change", "awareness"
    ):
        return TierResult(
            tier="C",
            rationale=f"{study_phase}_awareness",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # 5f. Phase I in a force-kept top-journal paper with notable signal
    if (
        study_phase == "phase1"
        and force_keep_reason
        and actionability in ("practice_change", "awareness")
    ):
        return TierResult(
            tier="C",
            rationale="phase1_top_journal_awareness",
            evidence_strength=evidence_strength,
            notify=False,
            actionability_advisory=actionability,
        )

    # ── Step 6: Default → NOISE ───────────────────────────────────────────────
    return TierResult(
        tier="NOISE",
        rationale=(
            f"no_tier_rule_matched: study_phase={study_phase!r}, "
            f"signal_type={signal_type!r}, "
            f"endpoint_met={primary_endpoint_met}, "
            f"actionability={actionability!r}, "
            f"source={confidence_source!r}"
        ),
        evidence_strength=evidence_strength,
        notify=False,
        actionability_advisory=actionability,
    )
