"""
Deterministic tier assignment — v2.

Replaces LLM impact_score + enforce_tier_mapping().

Architecture:
  The LLM extracts structured facts from the abstract (study_phase,
  primary_endpoint_type, primary_endpoint_met, effect_direction, hr_value,
  p_value_significant, hard_to_treat, reject_recommendation).

  This module converts those facts — plus the Gate 2 qualifying signal —
  into a final tier. All logic is deterministic, auditable, and tunable
  without touching the LLM prompt.

Tiers:
  A — Practice Impacting: FDA approval, guideline update, Phase III OS benefit
  B — Incremental: Phase III non-OS, Phase II randomized significant, landmark meta-analysis
  C — Horizon: Phase II single-arm significant, Phase II randomized trend, exploratory pooling
  NOISE: Negative primary, inconclusive, rejected by LLM, insufficient data

Design notes:
  • reject_recommendation=true always overrides to NOISE (LLM's one judgment call kept)
  • Qualifying signal is the primary classifier for FDA and GUIDELINE → always Tier A
  • hr_value modulates within Phase III OS: HR ≤ 0.82 → A, HR > 0.82 → B
  • hard_to_treat bumps Phase II results one tier when borderline
  • Important negative trials (p not significant, direction negative) → NOISE by default;
    the LLM should set reject_recommendation=false and the admin editor decides
"""

from __future__ import annotations


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
    phase       = extracted.get("study_phase", "other_or_unclear")
    ep_type     = extracted.get("primary_endpoint_type", "not_reported")
    ep_met      = extracted.get("primary_endpoint_met", False)
    direction   = extracted.get("effect_direction", "not_reported")
    hr          = extracted.get("hr_value")           # float or None
    p_sig       = extracted.get("p_value_significant", False)
    hard        = extracted.get("hard_to_treat", False)
    setting     = extracted.get("setting", "other_or_unclear")
    limitations = set(extracted.get("limitations_flags", []))

    # ── TIER A: Practice Impacting ───────────────────────────────────────────

    # FDA approval → always A (qualifying signal is the proof)
    if qualifying_signal == "FDA":
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

    phase     = extracted.get("study_phase", "?")
    ep_type   = extracted.get("primary_endpoint_type", "?")
    ep_met    = extracted.get("primary_endpoint_met", False)
    direction = extracted.get("effect_direction", "?")
    hr        = extracted.get("hr_value")
    p_sig     = extracted.get("p_value_significant", False)
    hard      = extracted.get("hard_to_treat", False)

    hr_str = f" (HR {hr:.2f})" if hr is not None else ""

    if tier == "A":
        if qualifying_signal in ("FDA", "GUIDELINE"):
            return f"Tier A — {qualifying_signal} qualifying signal"
        return f"Tier A — {phase}, {ep_type} benefit{hr_str}, p_sig={p_sig}"

    if tier == "B":
        return (f"Tier B — {phase}, {ep_type}, direction={direction}, "
                f"endpoint_met={ep_met}, p_sig={p_sig}{hr_str}")

    if tier == "C":
        hard_note = ", hard-to-treat" if hard else ""
        return (f"Tier C — {phase}, direction={direction}, "
                f"endpoint_met={ep_met}{hard_note}")

    return f"NOISE — no positive deterministic rule matched (direction={direction}, endpoint_met={ep_met})"
