"""
Unit tests for the deterministic tier assignment module:
  - triage/tier_logic.py  (compute_tier, tier_rationale)

These tests drive the tier logic without calling any LLM — they feed in
pre-populated `extracted` dicts exactly as Pass 2 would produce them.

Run from the pipeline/ directory:
  pytest tests/
"""

import sys
import os

_HERE = os.path.dirname(__file__)
_PIPELINE = os.path.dirname(_HERE)
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

import unittest
from carcinos_ingestion.triage.tier_logic import compute_tier, tier_rationale


# ---------------------------------------------------------------------------
# Helper — build an extracted dict with sensible defaults; override as needed.
# ---------------------------------------------------------------------------

def extracted(
    study_phase="phase3_rct",
    primary_endpoint_type="overall_survival",
    primary_endpoint_met=True,
    effect_direction="positive",
    hr_value=0.72,
    p_value_significant=True,
    hard_to_treat=False,
    reject_recommendation=False,
    signal_type="OTHER",
    elevates_to_practice_changing=False,
    setting="metastatic",
    limitations_flags=None,
) -> dict:
    return dict(
        study_phase=study_phase,
        primary_endpoint_type=primary_endpoint_type,
        primary_endpoint_met=primary_endpoint_met,
        effect_direction=effect_direction,
        hr_value=hr_value,
        p_value_significant=p_value_significant,
        hard_to_treat=hard_to_treat,
        reject_recommendation=reject_recommendation,
        signal_type=signal_type,
        elevates_to_practice_changing=elevates_to_practice_changing,
        setting=setting,
        limitations_flags=limitations_flags or [],
    )


# ===========================================================================
# SECTION 1: reject_recommendation gate (always NOISE)
# ===========================================================================

class TestRejectGate(unittest.TestCase):
    def test_reject_recommendation_true_always_noise(self):
        e = extracted(reject_recommendation=True)
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "NOISE"

    def test_reject_overrides_fda_signal_type(self):
        e = extracted(reject_recommendation=True, signal_type="FDA_APPROVAL")
        assert compute_tier(e, "FDA") == "NOISE"

    def test_reject_overrides_guideline_signal_type(self):
        e = extracted(reject_recommendation=True, signal_type="GUIDELINE_UPDATE")
        assert compute_tier(e, "GUIDELINE") == "NOISE"

    def test_reject_false_does_not_force_noise(self):
        e = extracted(reject_recommendation=False)
        tier = compute_tier(e, "PHASE_III_RANDOMIZED")
        assert tier != "NOISE"


# ===========================================================================
# SECTION 2: signal_type overrides (v3)
# ===========================================================================

class TestSignalTypeOverrides(unittest.TestCase):
    def test_fda_approval_signal_type_always_tier_a(self):
        e = extracted(signal_type="FDA_APPROVAL")
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"

    def test_guideline_update_signal_type_always_tier_a(self):
        e = extracted(signal_type="GUIDELINE_UPDATE")
        assert compute_tier(e, "META_ANALYSIS") == "A"

    def test_phase_iii_negative_signal_type_default_tier_b(self):
        e = extracted(signal_type="PHASE_III_NEGATIVE", elevates_to_practice_changing=False)
        assert compute_tier(e, "NEGATIVE_TRIAL") == "B"

    def test_phase_iii_negative_elevated_tier_a(self):
        e = extracted(signal_type="PHASE_III_NEGATIVE", elevates_to_practice_changing=True)
        assert compute_tier(e, "NEGATIVE_TRIAL") == "A"

    def test_safety_signal_default_tier_b(self):
        e = extracted(signal_type="SAFETY_SIGNAL", elevates_to_practice_changing=False)
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_safety_signal_elevated_tier_a(self):
        e = extracted(signal_type="SAFETY_SIGNAL", elevates_to_practice_changing=True)
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"


# ===========================================================================
# SECTION 3: Meta-analysis hard cap (never Tier A)
# ===========================================================================

class TestMetaAnalysisHardCap(unittest.TestCase):
    def test_meta_analysis_never_tier_a(self):
        # Even with positive, significant result → B at most
        e = extracted(
            study_phase="meta_analysis",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "META_ANALYSIS") != "A"

    def test_meta_analysis_significant_positive_is_tier_b(self):
        e = extracted(
            study_phase="meta_analysis",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "META_ANALYSIS") == "B"

    def test_meta_analysis_positive_direction_only_is_tier_c(self):
        e = extracted(
            study_phase="meta_analysis",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
        )
        assert compute_tier(e, "META_ANALYSIS") == "C"

    def test_meta_analysis_no_positive_signal_is_noise(self):
        e = extracted(
            study_phase="meta_analysis",
            effect_direction="inconclusive",
            primary_endpoint_met=False,
            p_value_significant=False,
        )
        assert compute_tier(e, "META_ANALYSIS") == "NOISE"

    def test_systematic_review_also_hard_capped(self):
        e = extracted(
            study_phase="systematic_review",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "META_ANALYSIS") != "A"

    def test_meta_analysis_with_fda_qualifying_signal_not_capped(self):
        """FDA qualifying signal bypasses the meta-analysis hard cap per code."""
        e = extracted(
            study_phase="meta_analysis",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        # With qualifying_signal=FDA, the FDA path fires first
        assert compute_tier(e, "FDA") == "A"


# ===========================================================================
# SECTION 4: TIER A — Practice Impacting
# ===========================================================================

class TestTierA(unittest.TestCase):
    def test_fda_qualifying_signal_always_a(self):
        e = extracted(study_phase="phase2_single_arm", effect_direction="positive", primary_endpoint_met=True)
        assert compute_tier(e, "FDA") == "A"

    def test_guideline_qualifying_signal_always_a(self):
        e = extracted(study_phase="other_or_unclear")
        assert compute_tier(e, "GUIDELINE") == "A"

    def test_guideline_update_study_phase_always_a(self):
        e = extracted(study_phase="guideline_update")
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"

    def test_phase3_rct_os_met_low_hr_is_tier_a(self):
        """Phase III RCT, OS primary, met, positive direction, HR ≤ 0.82 → A."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
            hr_value=0.72,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"

    def test_phase3_rct_os_met_no_hr_is_tier_a(self):
        """If HR is not reported, assume strong effect → A."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
            hr_value=None,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"

    def test_phase3_rct_os_met_hr_exactly_082_is_tier_a(self):
        """HR = 0.82 is the boundary — should still be A."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
            hr_value=0.82,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"

    def test_phase3_rct_os_noninferiority_met_is_tier_a(self):
        """Phase III RCT, OS, non-inferior, endpoint met → A (de-escalation proven)."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=True,
            effect_direction="non_inferior",
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "A"


# ===========================================================================
# SECTION 5: TIER B — Incremental
# ===========================================================================

class TestTierB(unittest.TestCase):
    def test_phase3_rct_os_met_high_hr_is_tier_b(self):
        """Phase III OS benefit but modest HR (> 0.82) → B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
            hr_value=0.88,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_phase3_rct_non_os_endpoint_met_is_tier_b(self):
        """Phase III, PFS primary, met → B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="progression_free_survival",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_phase3_rct_noninferiority_non_os_met_is_tier_b(self):
        """Phase III NI with non-OS endpoint met → B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="progression_free_survival",
            primary_endpoint_met=True,
            effect_direction="non_inferior",
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_phase3_rct_os_trend_strong_hr_tier_b(self):
        """Phase III, OS trend (not formally significant), HR ≤ 0.85 → B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
            hr_value=0.83,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_phase3_rct_os_trend_weak_hr_not_tier_b(self):
        """Phase III, OS trend, HR > 0.85 → not B (drops to NOISE or C)."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
            hr_value=0.92,
        )
        tier = compute_tier(e, "PHASE_III_RANDOMIZED")
        assert tier in ("C", "NOISE")

    def test_phase2_rct_met_significant_positive_is_tier_b(self):
        e = extracted(
            study_phase="phase2_rct",
            primary_endpoint_type="objective_response_rate",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "B"

    def test_phase2_rct_hard_to_treat_positive_endpoint_met_is_tier_b(self):
        """Hard-to-treat cancer + phase2_rct + positive + met → B."""
        e = extracted(
            study_phase="phase2_rct",
            primary_endpoint_met=True,
            p_value_significant=False,  # borderline
            effect_direction="positive",
            hard_to_treat=True,
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "B"

    def test_negative_phase3_qualifying_signal_is_tier_b(self):
        """Negative Phase III → always B (establishes what NOT to do)."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_met=False,
            effect_direction="negative",
        )
        assert compute_tier(e, "NEGATIVE_TRIAL") == "B"

    def test_major_conference_phase3_positive_is_tier_b(self):
        """Major conference + phase3_rct + positive → B (abstract-only, not yet published).

        Use a non-OS endpoint so the Phase III OS Tier A path doesn't fire first.
        """
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="progression_free_survival",
            effect_direction="positive",
            primary_endpoint_met=True,
            p_value_significant=True,
            hr_value=None,
        )
        assert compute_tier(e, "MAJOR_CONFERENCE") == "B"

    def test_meta_analysis_significant_positive_is_tier_b(self):
        e = extracted(
            study_phase="meta_analysis",
            primary_endpoint_met=True,
            p_value_significant=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "META_ANALYSIS") == "B"


# ===========================================================================
# SECTION 6: TIER C — Horizon
# ===========================================================================

class TestTierC(unittest.TestCase):
    def test_phase2_rct_positive_not_met_is_tier_c(self):
        """Phase II RCT, positive direction, primary endpoint NOT met → C."""
        e = extracted(
            study_phase="phase2_rct",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "C"

    def test_phase2_rct_hard_to_treat_inconclusive_is_tier_c(self):
        e = extracted(
            study_phase="phase2_rct",
            effect_direction="inconclusive",
            hard_to_treat=True,
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "C"

    def test_phase2_single_arm_positive_met_is_tier_c(self):
        e = extracted(
            study_phase="phase2_single_arm",
            primary_endpoint_met=True,
            effect_direction="positive",
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "C"

    def test_phase2_single_arm_hard_to_treat_positive_is_tier_c(self):
        e = extracted(
            study_phase="phase2_single_arm",
            effect_direction="positive",
            hard_to_treat=True,
        )
        assert compute_tier(e, "PHASE_II_RANDOMIZED") == "C"

    def test_negative_phase2_qualifying_signal_is_tier_c(self):
        """Negative Phase II → C (hypothesis-generating)."""
        e = extracted(
            study_phase="phase2_rct",
            primary_endpoint_met=False,
            effect_direction="negative",
        )
        assert compute_tier(e, "NEGATIVE_TRIAL") == "C"

    def test_conference_abstract_positive_is_tier_c(self):
        """Major conference + positive direction (non-Phase III) → C."""
        e = extracted(
            study_phase="phase2_rct",
            effect_direction="positive",
            primary_endpoint_met=False,
        )
        assert compute_tier(e, "MAJOR_CONFERENCE") == "C"

    def test_top_journal_positive_is_tier_c(self):
        e = extracted(
            study_phase="other_or_unclear",
            effect_direction="positive",
        )
        assert compute_tier(e, "TOP_JOURNAL") == "C"

    def test_regulatory_phase2_positive_is_tier_c(self):
        e = extracted(
            study_phase="phase2_single_arm",
            effect_direction="positive",
        )
        assert compute_tier(e, "REGULATORY_PHASE_II") == "C"

    def test_systematic_review_positive_direction_is_tier_c(self):
        e = extracted(
            study_phase="systematic_review",
            effect_direction="positive",
            primary_endpoint_met=False,
        )
        assert compute_tier(e, "META_ANALYSIS") == "C"


# ===========================================================================
# SECTION 7: NOISE
# ===========================================================================

class TestNoise(unittest.TestCase):
    def test_no_positive_rule_matched_is_noise(self):
        """Phase III RCT with no significant positive endpoint → NOISE."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="inconclusive",
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "NOISE"

    def test_phase2_single_arm_not_met_not_hard_is_noise(self):
        e = extracted(
            study_phase="phase2_single_arm",
            primary_endpoint_met=False,
            effect_direction="positive",
            hard_to_treat=False,
        )
        tier = compute_tier(e, "PHASE_II_RANDOMIZED")
        # phase2_single_arm + positive + NOT met + NOT hard → should be NOISE
        # (the C rules require either ep_met=True or hard_to_treat=True)
        assert tier == "NOISE"

    def test_meta_analysis_inconclusive_is_noise(self):
        e = extracted(
            study_phase="meta_analysis",
            effect_direction="inconclusive",
            primary_endpoint_met=False,
        )
        assert compute_tier(e, "META_ANALYSIS") == "NOISE"

    def test_other_phase_no_matching_rule_is_noise(self):
        e = extracted(
            study_phase="other_or_unclear",
            effect_direction="negative",
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "NOISE"


# ===========================================================================
# SECTION 8: tier_rationale (sanity checks — it should not raise and should
#             return a non-empty string)
# ===========================================================================

class TestTierRationale(unittest.TestCase):
    def test_rationale_for_tier_a_not_empty(self):
        e = extracted(study_phase="phase3_rct", primary_endpoint_type="overall_survival",
                      primary_endpoint_met=True, p_value_significant=True,
                      effect_direction="positive", hr_value=0.72)
        r = tier_rationale(e, "PHASE_III_RANDOMIZED", "A")
        assert isinstance(r, str) and len(r) > 0

    def test_rationale_for_tier_b_not_empty(self):
        e = extracted(study_phase="phase3_rct", primary_endpoint_type="pfs",
                      primary_endpoint_met=True, p_value_significant=True,
                      effect_direction="positive")
        r = tier_rationale(e, "PHASE_III_RANDOMIZED", "B")
        assert isinstance(r, str) and len(r) > 0

    def test_rationale_for_tier_c_not_empty(self):
        e = extracted(study_phase="phase2_rct", effect_direction="positive",
                      primary_endpoint_met=False)
        r = tier_rationale(e, "PHASE_II_RANDOMIZED", "C")
        assert isinstance(r, str) and len(r) > 0

    def test_rationale_for_noise_not_empty(self):
        e = extracted(study_phase="other_or_unclear", effect_direction="inconclusive")
        r = tier_rationale(e, "PHASE_III_RANDOMIZED", "NOISE")
        assert isinstance(r, str) and len(r) > 0

    def test_rationale_mentions_reject_when_applicable(self):
        e = extracted(reject_recommendation=True)
        r = tier_rationale(e, "PHASE_III_RANDOMIZED", "NOISE")
        assert "reject" in r.lower() or "noise" in r.lower()

    def test_rationale_for_fda_signal_type(self):
        e = extracted(signal_type="FDA_APPROVAL")
        r = tier_rationale(e, "FDA", "A")
        assert "FDA" in r or "fda" in r.lower()

    def test_rationale_for_negative_trial_tier_b(self):
        e = extracted(study_phase="phase3_rct", primary_endpoint_met=False,
                      effect_direction="negative")
        r = tier_rationale(e, "NEGATIVE_TRIAL", "B")
        assert "negative" in r.lower() or "NOT" in r


# ===========================================================================
# SECTION 9: Edge cases and boundary conditions
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_hr_exactly_083_os_trend_is_tier_b(self):
        """HR = 0.83 (≤ 0.85), no formal significance → B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
            hr_value=0.83,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_hr_exactly_085_os_trend_is_tier_b(self):
        """HR = 0.85 is at the boundary — should still be B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
            hr_value=0.85,
        )
        assert compute_tier(e, "PHASE_III_RANDOMIZED") == "B"

    def test_hr_086_os_trend_not_tier_b(self):
        """HR = 0.86 (> 0.85) without significance → not B."""
        e = extracted(
            study_phase="phase3_rct",
            primary_endpoint_type="overall_survival",
            primary_endpoint_met=False,
            p_value_significant=False,
            effect_direction="positive",
            hr_value=0.86,
        )
        tier = compute_tier(e, "PHASE_III_RANDOMIZED")
        assert tier in ("C", "NOISE")

    def test_missing_fields_default_gracefully(self):
        """compute_tier should not raise on a dict with missing optional keys."""
        e = {"study_phase": "phase3_rct", "primary_endpoint_met": True}
        # Should not raise, should return a valid tier string
        tier = compute_tier(e, "PHASE_III_RANDOMIZED")
        assert tier in ("A", "B", "C", "NOISE")

    def test_empty_dict_returns_noise(self):
        """An empty extracted dict should return NOISE without raising."""
        tier = compute_tier({}, "PHASE_III_RANDOMIZED")
        assert tier == "NOISE"

    def test_all_tiers_are_valid_strings(self):
        """All possible paths should return one of the four valid tier codes."""
        valid = {"A", "B", "C", "NOISE"}
        configs = [
            (extracted(reject_recommendation=True), "PHASE_III_RANDOMIZED"),
            (extracted(signal_type="FDA_APPROVAL"), "FDA"),
            (extracted(signal_type="GUIDELINE_UPDATE"), "GUIDELINE"),
            (extracted(signal_type="PHASE_III_NEGATIVE"), "NEGATIVE_TRIAL"),
            (extracted(study_phase="phase3_rct", primary_endpoint_type="overall_survival",
                       primary_endpoint_met=True, p_value_significant=True,
                       effect_direction="positive", hr_value=0.72), "PHASE_III_RANDOMIZED"),
            (extracted(study_phase="phase3_rct", primary_endpoint_type="overall_survival",
                       primary_endpoint_met=True, p_value_significant=True,
                       effect_direction="positive", hr_value=0.88), "PHASE_III_RANDOMIZED"),
            (extracted(study_phase="phase2_rct", primary_endpoint_met=True,
                       p_value_significant=True, effect_direction="positive"), "PHASE_II_RANDOMIZED"),
            (extracted(study_phase="phase2_rct", primary_endpoint_met=False,
                       effect_direction="positive"), "PHASE_II_RANDOMIZED"),
            (extracted(study_phase="phase2_single_arm", primary_endpoint_met=True,
                       effect_direction="positive"), "PHASE_II_RANDOMIZED"),
            (extracted(study_phase="meta_analysis", primary_endpoint_met=True,
                       p_value_significant=True, effect_direction="positive"), "META_ANALYSIS"),
            (extracted(study_phase="other_or_unclear",
                       effect_direction="inconclusive"), "PHASE_III_RANDOMIZED"),
        ]
        for e, qs in configs:
            tier = compute_tier(e, qs)
            assert tier in valid, f"Invalid tier '{tier}' for qualifying_signal={qs}"
if __name__ == '__main__':
    unittest.main()
