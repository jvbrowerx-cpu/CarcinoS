"""
Strict JSON schemas for OpenAI structured outputs (spec §3).

Two passes:
  PASS 1 (cheap triage)  → keep/drop + classification + relevance hint
  PASS 2 (deep review)   → full extraction + tier assignment

Keep schemas exactly aligned with what the spec doc describes so the
post-LLM logic in pipeline.py can enforce thresholds deterministically.
"""

PASS1_SCHEMA = {
    "name": "carcinos_pass1_triage",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keep": {"type": "boolean"},
            "drop_reason": {
                "type": ["string", "null"],
                "enum": [
                    None,
                    "not_oncology",
                    "wrong_disease_site",
                    "non_human_only",
                    "non_data_opinion_only",
                    "duplicate",
                    "insufficient_info_and_low_relevance",
                ],
            },
            "cancer_site_confirmed": {"type": "boolean"},
            "category": {
                "type": "string",
                "enum": ["trial", "guideline", "epi", "translational", "survivorship", "other"],
            },
            "study_design": {
                "type": "string",
                "enum": [
                    "phase3_rct",
                    "phase2_trial",
                    "phase1_trial",
                    "observational_cohort",
                    "registry_population",
                    "meta_analysis",
                    "systematic_review",
                    "guideline_consensus",
                    "diagnostic_screening",
                    "preclinical",
                    "case_report",
                    "other_or_unclear",
                ],
            },
            "modalities": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "radiation", "brachytherapy", "surgery",
                        "chemotherapy", "immunotherapy", "targeted",
                        "parp", "antiangiogenic", "screening",
                        "vaccine", "supportive", "imaging",
                        "biomarker", "cellular_therapy", "other",
                    ],
                },
                "minItems": 0,
                "maxItems": 6,
            },
            "relevance_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "priority_hint": {"type": "string", "enum": ["high", "medium", "low"]},
            "one_line_rationale": {"type": "string", "maxLength": 220},
        },
        "required": [
            "keep",
            "drop_reason",
            "cancer_site_confirmed",
            "category",
            "study_design",
            "modalities",
            "relevance_score",
            "priority_hint",
            "one_line_rationale",
        ],
    },
}


PASS2_SCHEMA = {
    "name": "carcinos_pass2_deep_review",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cancer_site_subtype": {"type": "string", "maxLength": 80},
            "setting": {
                "type": "string",
                "enum": [
                    "screening_prevention",
                    "localized_definitive",
                    "adjuvant",
                    "neoadjuvant",
                    "recurrent_metastatic",
                    "maintenance",
                    "survivorship_supportive",
                    "diagnostic",
                    "other_or_unclear",
                ],
            },
            "category": {
                "type": "string",
                "enum": ["trial", "guideline", "epi", "translational", "survivorship", "other"],
            },
            "study_design": {
                "type": "string",
                "enum": [
                    "phase3_rct", "phase2_trial", "phase1_trial",
                    "observational_cohort", "registry_population",
                    "meta_analysis", "systematic_review",
                    "guideline_consensus", "diagnostic_screening",
                    "preclinical", "case_report", "other_or_unclear",
                ],
            },
            "population": {"type": "string", "maxLength": 240},
            "intervention": {"type": "string", "maxLength": 240},
            "comparator": {"type": "string", "maxLength": 240},
            "primary_endpoint": {"type": "string", "maxLength": 160},
            "key_results": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "effect_size": {"type": "string", "maxLength": 120},
                    "p_value_or_ci": {"type": "string", "maxLength": 120},
                    "absolute_difference": {"type": "string", "maxLength": 120},
                    "toxicity_qol_signal": {"type": "string", "maxLength": 160},
                },
                "required": [
                    "effect_size",
                    "p_value_or_ci",
                    "absolute_difference",
                    "toxicity_qol_signal",
                ],
            },
            "evidence_strength": {"type": "string", "enum": ["A", "B", "C", "D"]},
            "impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "alert_tier": {
                "type": "string",
                "enum": ["practice_changing", "incremental", "horizon", "noise"],
            },
            "why_it_matters": {
                "type": "array",
                "items": {"type": "string", "maxLength": 180},
                "minItems": 2,
                "maxItems": 4,
            },
            "who_should_care": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "med_onc", "rad_onc", "surg_onc",
                        "gyn_onc", "uro_onc", "hem_onc",
                        "neuro_onc", "derm_onc", "thoracic_surg",
                        "pcp_screening", "survivorship_team",
                    ],
                },
                "minItems": 1,
                "maxItems": 4,
            },
            "limitations_flags": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "immature_os",
                        "surrogate_endpoint_only",
                        "single_arm",
                        "small_n",
                        "subgroup_only",
                        "preclinical_only",
                        "observational_confounding",
                        "unclear_methods",
                        "access_generalizability",
                    ],
                },
                "minItems": 0,
                "maxItems": 5,
            },
            "regimen_description": {
                "type": "string",
                "maxLength": 320,
                "description": "Natural-language description of the study design and treatment arms including doses/schedule where reported. Example: 'Open-label phase III; cisplatin + PORT (66 Gy, cisplatin 100 mg/m² q3w ×3) vs same backbone + nivolumab (peri-CRT + adjuvant schedule).'"
            },
            "carcinos_one_liner": {"type": "string", "maxLength": 280},
            "evidence_quotes": {
                "type": "array",
                "description": "1-3 short quotes from the source abstract supporting key claims (anti-hallucination grounding)",
                "items": {"type": "string", "maxLength": 280},
                "minItems": 1,
                "maxItems": 3,
            },
        },
        "required": [
            "cancer_site_subtype",
            "setting",
            "category",
            "study_design",
            "population",
            "intervention",
            "comparator",
            "primary_endpoint",
            "key_results",
            "evidence_strength",
            "impact_score",
            "alert_tier",
            "why_it_matters",
            "who_should_care",
            "limitations_flags",
            "regimen_description",
            "carcinos_one_liner",
            "evidence_quotes",
        ],
    },
}
