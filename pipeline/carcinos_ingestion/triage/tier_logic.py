"""
Deterministic tier assignment — v3 (signal-centric).

Architecture:
  The LLM extracts structured facts from the abstract, including a new
  signal_type field that classifies the kind of oncology signal this
  evidence source represents. This module uses signal_type as the primary
  classifier, falling back to qualifying_signal + study_phase for backward
  compatibility.

  Tier assignment is deterministic, auditable, and tunable without touching
  the LLM prompt.

Tiers:
  A — Practice Impacting: FDA approval, guideline update, Phase III OS benefit
  B — Incremental: Phase III non-OS, Phase II randomized significant, landmark meta-analysis,
                   negative Phase III RCT (establishes what NOT to do)
  C — Horizon: Phase II single-arm significant, Phase II randomized trend, exploratory pooling,
               negative Phase II randomized trial
  NOISE: Inconclusive, rejected by LLM, insufficient data

Design notes (v3):
  • signal_type (from LLM) is the first-pass classifier. It captures the
    *type* of signal regardless of where it was published.
  • qualifying_signal (from deterministic gate) is used for FDA and GUIDELINE
    as a hard override — these always yield Tier A.
  • reject_recommendation=true always overrides to NOISE (LLM's one judgment call).
  • hr_value modulates within Phase III OS: HR ≤ 0.82 → A, HR > 0.82 → B.
  • hard_to_treat bumps Phase II results one tier when borderline.
  • PHASE_III_NEGATIVE always Tier B regardless of study_phase label.
  • DE_ESCALATION treated as a positive signal if endpoint was met.
"""

from __future__ import annotations


# Signal types that always yield Tier A regardless of other fields
_ALWAYS_TIER_A_SIGNAL_TYPES = frozenset({
    "FDA_APPROVAL",
    "GUIDELINE_UPDATE",
})

# Signal types that DEFAULT to Tier B but can be elevated to Tier A.
#
# PHASE_III_NEGATIVE defaults to B (establishes what NOT to do), but can be
# Tier A when it stops adoption of a widely-used treatment, invalidates a
# standard, reverses clinical enthusiasm, or directly affects guideline
# interpretation. The LLM sets elevates_to_practice_changing=True for these.
#
# SAFETY_SIGNAL defaults to B but can be Tier A for black-box warnings, drug
# withdrawals, excess mortality findings, or signals requiring immediate
# changes to prescribing, patient selection, or monitoring.
#
# Neither is ever hard-capped at B — clinical judgment (via the LLM's
# elevates_to_practice_changing field) determines when elevation applies.
_DEFAULT_TIER_B_SIGNAL_TYPES = frozenset({
    "PHASE_III_NEGATIVE",
    "SAFETY_SIGNAL",
})


def compute_tier(extracted: dict, qualifying_signal: str) -> str:
    """
    Compute the final tier from LLM-extracted structured fields.

    Args:
        extracted:  The parsed Pass 2 JSON response from the LLM.
        qualifying_signal: The Gate 2 qualifying signal code (e.g. QS_PHASE_III_RANDOMIZED).

    Returns:
        "A" | "B" | "C" | "NOISE"
    """

    # ── Reject gate ──────────────────────────────────────────────────────────
    # LLM's one judgment call: is this noise despite passing signal scoring?
    if extracted.get("reject_recommendation", False):
        return "NOISE"

    # ── Extract fields ───────────────────────────────────────────────────────
    phase        = extracted.get("study_phase", "other_or_unclear")
    ep_type      = extracted.get("primary_endpoint_type", "not_reported")
    ep_met       = extracted.get("primary_endpoint_met", False)
    direction    = extracted.get("effect_direction", "not_reported")
    hr           = extracted.get("hr_value")           # float or None
    p_sig        = extracted.get("p_value_significant", False)
    hard         = extracted.get("hard_to_treat", False)
    setting      = extracted.get("setting", "other_or_unclear")
    limitations  = set(extracted.get("limitations_flags", []))
    signal_type  = extracted.get("signal_type", "OTHER")  # new in v3

    # ── Hard cap: single-arm Phase II can never be Tier A ────────────────────
    # A window-of-opportunity trial, single-arm Phase II, or any study without
    # a comparator arm cannot be Practice Impacting regardless of how Gate 2
    # classified the qualifying_signal (e.g., an FDA-approved drug in a new
    # window trial may trigger an FDA signal — that does not make the trial
    # practice-changing). Route directly to Tier C logic, bypassing all Tier A
    # fast-paths. Surrogate-only endpoints (Ki-67, pCR) get no exemption.
    if phase == "phase2_single_arm" and "single_arm" in limitations:
        if direction == "positive" and ep_met:
            return "C"
        if hard and direction == "positive":
            return "C"
        return "NOISE"

    # ── Signal-type overrides (v3) ────────────────────────────────────────────
    # signal_type from the LLM classifies the KIND of signal, independently of
    # where it was published. These take precedence over study_phase.
    #
    # FDA_APPROVAL and GUIDELINE_UPDATE are always Tier A — belt + suspenders
    # with the qualifying_signal block below.
    if signal_type in _ALWAYS_TIER_A_SIGNAL_TYPES:
        return "A"

    # PHASE_III_NEGATIVE and SAFETY_SIGNAL default to Tier B, but can be
    # elevated to Tier A when the LLM sets elevates_to_practice_changing=True.
    #
    # Tier A cases:
    #   PHASE_III_NEGATIVE — trial stops adoption of a near-standard treatment,
    #     invalidates a standard, reverses clinical enthusiasm, or directly
    #     affects guideline interpretation.
    #   SAFETY_SIGNAL — black-box warning, drug withdrawal, excess mortality,
    #     or finding that requires immediate changes to prescribing/monitoring.
    #
    # Tier B (default):
    #   Any negative trial that clarifies uncertainty without overturning
    #   an established standard ("establishes what NOT to do").
    #   Any safety signal that is notable but not immediately practice-changing.
    if signal_type in _DEFAULT_TIER_B_SIGNAL_TYPES:
        elevates = extracted.get("elevates_to_practice_changing", False)
        if elevates:
            return "A"
        return "B"

    # ── Meta-analysis / systematic review HARD CAP ──────────────────────────────
    #
    # Meta-analyses and systematic reviews synthesise existing evidence — they do
    # not generate new primary data and can NEVER be Practice Impacting (Tier A),
    # regardless of how the LLM classified study_phase.
    #
    # This guard exists primarily to catch the common LLM error of tagging a
    # "meta-analysis of Phase III RCTs" as study_phase="phase3_rct", which would
    # otherwise slip through the Phase III OS benefit path below and reach Tier A.
    #
    # FDA approvals and formal guideline updates are the only exception — an FDA
    # label update announced alongside a meta-analysis is still Tier A because the
    # qualifying signal is the regulatory action, not the study design.
    #
    # Consensus reviews from societies NOT in the formal guideline-update list
    # (NCCN / ASCO / ESMO / ASTRO / ASH) are also caught here: a SNO/EANO
    # consensus review is a systematic_review, not a guideline_update.
    if phase in ("meta_analysis", "systematic_review") and not (
        (qualifying_signal == "FDA" and signal_type == "FDA_APPROVAL")
        or qualifying_signal == "GUIDELINE"
    ):
        # Quantitative meta-analysis with a significant positive result → Tier B
        if ep_met and p_sig and direction in ("positive", "non_inferior"):
            return "B"
        # Any positive direction → Tier C (noteworthy but not definitive)
        if direction == "positive":
            return "C"
        # Otherwise noise
        return "NOISE"

    # ── QS_NEGATIVE_TRIAL: Randomized trial that failed primary endpoint ────────
    #
    # A major randomized trial failing its primary endpoint IS practice-changing —
    # it establishes what NOT to do, prevents futile treatments, and often changes
    # standard of care by eliminating a previously expected treatment option.
    #
    # Phase III negative → Tier B (Incremental): landmark result regardless of direction.
    # Phase II negative → Tier C (Horizon): interesting but not definitive.
    #
    # The reject gate above already handled reject_recommendation=true.
    if qualifying_signal == "NEGATIVE_TRIAL":
        if phase == "phase3_rct":
            return "B"
        # Phase II negative → Horizon
        return "C"

    # ── TIER A: Practice Impacting ───────────────────────────────────────────

    # FDA approval → Tier A only when Gate 2 AND LLM both agree.
    # Gate 2's _FDA_RE fires on "FDA-approved [drug]" used as background context
    # in any abstract. Requiring signal_type == "FDA_APPROVAL" ensures the LLM
    # independently confirmed this is an actual regulatory approval announcement,
    # not merely a trial that uses an FDA-approved agent.
    if qualifying_signal == "FDA" and signal_type == "FDA_APPROVAL":
        return "A"

    # Guideline update (formal NCCN/ASCO/ESMO/ASTRO revision) → always A
    if qualifying_signal == "GUIDELINE" or phase == "guideline_update":
        return "A"

    # Phase III RCT with overall survival benefit
    if phase == "phase3_rct" and ep_type == "overall_survival":
        if ep_met and p_sig and direction == "positive":
            # Strong OS benefit (HR ≤ 0.82) → A; modest (HR > 0.82) → B
            if hr is None or hr <= 0.82:
                return "A"
            # HR > 0.82: significant OS but modest effect — Incremental
            return "B"

    # Phase III RCT — non-inferiority with OS as endpoint (de-escalation proven)
    # e.g. "omitting RT is non-inferior for OS in low-risk disease" → practice changing
    if (phase == "phase3_rct"
            and ep_type == "overall_survival"
            and direction == "non_inferior"
            and ep_met):
        return "A"

    # ── TIER B: Incremental ──────────────────────────────────────────────────

    # Phase III RCT — any significant non-OS primary endpoint met
    if phase == "phase3_rct" and ep_met and p_sig and direction in ("positive", "non_inferior"):
        return "B"

    # Phase III RCT — OS trend without formal significance but strong HR
    # (e.g. OS HR 0.82 p=0.07 in hard-to-treat cancer — still noteworthy)
    if (phase == "phase3_rct"
            and ep_type == "overall_survival"
            and direction == "positive"
            and hr is not None and hr <= 0.85):
        return "B"

    # Phase III RCT — non-inferiority confirmed (de-escalation), non-OS endpoint
    if phase == "phase3_rct" and direction == "non_inferior" and ep_met:
        return "B"

    # Phase II RCT — significant primary endpoint met
    if phase == "phase2_rct" and ep_met and p_sig and direction == "positive":
        return "B"

    # Phase II RCT — hard-to-treat cancer with positive direction, even if
    # formal threshold borderline (e.g. p=0.06 in GBM or pancreatic)
    if (phase == "phase2_rct"
            and hard
            and direction == "positive"
            and ep_met):
        return "B"

    # Meta-analysis — quantitative pooling with significant, positive/NI result
    if (phase == "meta_analysis"
            and ep_met and p_sig
            and direction in ("positive", "non_inferior")):
        return "B"

    # Major conference LBA for Phase III with any positive endpoint
    # (abstract-only, full data pending — treat as Incremental until published)
    if qualifying_signal == "MAJOR_CONFERENCE" and phase == "phase3_rct" and direction == "positive":
        return "B"

    # ── TIER C: Horizon ──────────────────────────────────────────────────────

    # Phase II RCT — positive direction but primary endpoint not formally met
    if phase == "phase2_rct" and direction == "positive" and not ep_met:
        return "C"

    # Phase II RCT — inconclusive but in hard-to-treat disease (worth flagging)
    if phase == "phase2_rct" and hard and direction in ("positive", "inconclusive"):
        return "C"

    # Phase II single-arm — significant positive response in any setting
    if (phase == "phase2_single_arm"
            and direction == "positive"
            and ep_met):
        return "C"

    # Phase II single-arm — compelling ORR or response in rare/hard-to-treat cancer
    if phase == "phase2_single_arm" and hard and direction == "positive":
        return "C"

    # Meta-analysis / systematic review — positive direction but not formally pooled
    if phase in ("meta_analysis", "systematic_review") and direction == "positive":
        return "C"

    # Conference abstract — early signal, no formal result yet
    if qualifying_signal == "MAJOR_CONFERENCE" and direction == "positive":
        return "C"

    # Top-journal catch-all — surfaced via TOP_JOURNAL signal, positive finding
    if qualifying_signal == "TOP_JOURNAL" and direction == "positive":
        return "C"

    # Regulatory Phase II (rare/orphan) — any positive signal worth flagging
    if qualifying_signal == "REGULATORY_PHASE_II" and direction == "positive":
        return "C"

    # ── NOISE ────────────────────────────────────────────────────────────────
    return "NOISE"


def tier_rationale(extracted: dict, qualifying_signal: str, tier: str) -> str:
    """
    One-line human-readable explanation of why this tier was assigned.
    Written to the admin portal for editor transparency.
    """
    if extracted.get("reject_recommendation"):
        return "LLM flagged as noise — reject_recommendation=true"

    phase       = extracted.get("study_phase", "?")
    ep_type     = extracted.get("primary_endpoint_type", "?")
    ep_met      = extracted.get("primary_endpoint_met", False)
    direction   = extracted.get("effect_direction", "?")
    hr          = extracted.get("hr_value")
    p_sig       = extracted.get("p_value_significant", False)
    hard        = extracted.get("hard_to_treat", False)
    signal_type = extracted.get("signal_type", "OTHER")

    hr_str = f" (HR {hr:.2f})" if hr is not None else ""

    elevates = extracted.get("elevates_to_practice_changing", False)

    # Signal-type overrides (v3) — include signal_type in rationale
    if signal_type in _ALWAYS_TIER_A_SIGNAL_TYPES:
        return f"Tier A — signal_type={signal_type}"
    if signal_type in _DEFAULT_TIER_B_SIGNAL_TYPES:
        if elevates and tier == "A":
            return (f"Tier A — signal_type={signal_type}, elevates_to_practice_changing=true "
                    f"(stops adoption / invalidates standard / major safety action)")
        return f"Tier B — signal_type={signal_type} (default; elevates_to_practice_changing=false)"

    if qualifying_signal == "NEGATIVE_TRIAL" or signal_type == "PHASE_III_NEGATIVE":
        if tier == "B":
            return f"Tier B — negative Phase III ({ep_type}); establishes what NOT to do"
        return f"Tier C — negative Phase II ({ep_type}); hypothesis-generating"

    if phase in ("meta_analysis", "systematic_review") and qualifying_signal not in ("FDA", "GUIDELINE"):
        if tier == "B":
            return "Tier B — meta-analysis/systematic review (hard cap: never Tier A); significant positive pooled result"
        if tier == "C":
            return "Tier C — meta-analysis/systematic review (hard cap: never Tier A); positive direction without formal significance"
        return "NOISE — meta-analysis/systematic review with no positive signal"

    if tier == "A":
        if qualifying_signal in ("FDA", "GUIDELINE") or signal_type in _ALWAYS_TIER_A_SIGNAL_TYPES:
            return f"Tier A — {signal_type or qualifying_signal} qualifying signal"
        return f"Tier A — {phase}, {ep_type} benefit{hr_str}, p_sig={p_sig}"

    if tier == "B":
        return (f"Tier B — signal_type={signal_type}, {phase}, {ep_type}, "
                f"direction={direction}, endpoint_met={ep_met}, p_sig={p_sig}{hr_str}")

    if tier == "C":
        hard_note = ", hard-to-treat" if hard else ""
        return (f"Tier C — signal_type={signal_type}, {phase}, "
                f"direction={direction}, endpoint_met={ep_met}{hard_note}")

    return (f"NOISE — no positive deterministic rule matched "
            f"(signal_type={signal_type}, direction={direction}, endpoint_met={ep_met})")
