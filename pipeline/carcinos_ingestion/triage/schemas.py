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

            # ── Structured fields for deterministic tier computation ──────────
            # These replace impact_score + alert_tier. The LLM extracts facts;
            # code converts them to a tier. All scoring is deterministic.

            "study_phase": {
                "type": "string",
                "enum": [
                    "phase3_rct",           # Phase III randomized controlled trial
                    "phase2_rct",           # Phase II randomized (comparator arm present)
                    "phase2_single_arm",    # Phase II single-arm (no comparator)
                    "phase1",               # Phase I (dose-finding, safety)
                    "meta_analysis",        # Quantitative pooled analysis / IPD meta-analysis
                    "systematic_review",    # Qualitative systematic review (no pooling)
                    "guideline_update",     # Formal guideline revision by NCCN/ASCO/ESMO/ASTRO
                    "fda_approval",         # FDA approval record
                    "observational",        # Cohort, registry, real-world data
                    "other_or_unclear",
                ],
            },
            "primary_endpoint_type": {
                "type": "string",
                "enum": [
                    "overall_survival",
                    "progression_free_survival",
                    "disease_free_survival",
                    "event_free_survival",
                    "objective_response_rate",
                    "non_inferiority",      # trial designed as noninferiority / de-escalation
                    "pathologic_response",  # pCR, MPR
                    "locoregional_control",
                    "other",
                    "not_reported",
                ],
            },
            "primary_endpoint_met": {
                "type": "boolean",
                "description": "True if the pre-specified primary endpoint was formally met at the pre-defined significance threshold. False if the primary endpoint was not met (negative trial or missed primary). Use false, not null, when the result is clear.",
            },
            "effect_direction": {
                "type": "string",
                "enum": [
                    "positive",       # intervention shows benefit
                    "non_inferior",   # pre-specified NI margin confirmed
                    "negative",       # intervention shows no benefit or harm
                    "inconclusive",   # mixed or unclear signal
                    "not_reported",   # insufficient data in abstract
                ],
            },
            "hr_value": {
                "type": ["number", "null"],
                "description": "Primary endpoint hazard ratio as a decimal (e.g. 0.76). Null if HR not reported or endpoint is not time-to-event.",
            },
            "p_value_significant": {
                "type": "boolean",
                "description": "True if p-value for the primary endpoint is below the pre-specified alpha (typically 0.05). False if p >= alpha. Use false when the trial is negative.",
            },
            "hard_to_treat": {
                "type": "boolean",
                "description": "True if the cancer type is a recognized hard-to-treat entity: GBM, SCLC, pancreatic, biliary/cholangiocarcinoma, mesothelioma, gastric, DIPG, appendiceal, or any cancer with median OS < 12 months in the studied setting.",
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
            "why_it_surfaced": {
                "type": "string",
                "maxLength": 320,
                "description": "Plain-language reason the signal-scoring engine kept this paper (e.g. 'Phase III RCT with OS benefit in first-line NSCLC — FDA approval reported').",
            },
            "radiation_oncology_relevance": {
                "type": "string",
                "enum": ["direct", "indirect", "none"],
                "description": "direct = changes RT dose, field, or technique; indirect = affects combined-modality decisions; none = systemic-only with no RT implication.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "moderate", "low"],
                "description": "Your confidence that this paper belongs in the admin portal. high = landmark RCT or FDA approval; moderate = solid Phase II or guideline; low = unclear, thin, or likely noise.",
            },
            "reject_recommendation": {
                "type": "boolean",
                "description": "Set true if you believe this item is noise despite passing the signal gate. If true AND tier is B or C, the pipeline will hard-drop this card.",
            },
            "trial_name": {
                "type": ["string", "null"],
                "maxLength": 80,
                "description": (
                    "Canonical trial acronym or name if this paper reports primary or updated "
                    "results of a named clinical trial (e.g. 'FLAURA2', 'CheckMate-816', 'LAURA', "
                    "'PATHOS'). Use the shortest widely-recognized name. "
                    "Write null if this is not a named trial, is a review/meta-analysis, "
                    "or the trial name cannot be determined from the abstract."
                ),
            },

            # ── Negative/safety signal elevation ─────────────────────────────
            # Set true when a PHASE_III_NEGATIVE or SAFETY_SIGNAL rises to Tier A
            # because it actively forces a practice change NOW — stopping adoption
            # of a treatment, reversing clinical enthusiasm, invalidating a standard,
            # triggering a black-box warning, drug withdrawal, or excess mortality
            # finding that changes prescribing, monitoring, or patient selection.
            # Leave false for negative results that clarify uncertainty without
            # overturning an established standard.
            "elevates_to_practice_changing": {
                "type": "boolean",
                "description": (
                    "For PHASE_III_NEGATIVE: true if this result stops adoption of a widely-used "
                    "or expected treatment, invalidates a standard of care, reverses clinical "
                    "enthusiasm, or directly affects guideline interpretation. "
                    "Example: a Phase III showing that adding chemotherapy to standard RT "
                    "in a setting where it had become near-standard has NO benefit → true. "
                    "Example: a negative Phase III in an experimental arm that was never "
                    "adopted → false (Tier B). "
                    "For SAFETY_SIGNAL: true if it involves a new black-box warning, drug "
                    "withdrawal, excess mortality finding, or requires immediate changes to "
                    "prescribing, patient selection, or monitoring. "
                    "For all other signal_types: always false."
                ),
            },

            # ── Clinical actionability ───────────────────────────────────────
            # Assessed here, while the LLM has the full abstract + regimen in
            # context — avoiding a separate third LLM pass.
            # tier_logic.py rules:
            #   Tier A (FDA / guideline / Phase III OS): field is LOGGED but
            #     never used as a veto — these are actionable by definition.
            #   Tier B / C: "inert" → hard-drop to NOISE / quarantine.
            #   "background" → kept as Tier C with a warning tag on the card.
            "clinical_actionability": {
                "type": "string",
                "enum": [
                    "practice_change",  # clinician would alter an active decision NOW
                    "awareness",        # shifts future readiness or tumor-board discussion
                    "background",       # biologically interesting, no near-term impact
                    "inert",            # no plausible impact on any clinical decision
                ],
                "description": (
                    "Would a practicing oncologist or radiation oncologist plausibly change "
                    "awareness, discussion, sequencing, dose, volume, referral, or systemic "
                    "therapy choice because of this finding? "
                    "practice_change = active decision changes NOW. "
                    "awareness = shifts future readiness or tumor-board discussion. "
                    "background = biologically interesting but no near-term impact. "
                    "inert = no plausible clinical relevance whatsoever. "
                    "An FDA approval or Phase III OS benefit is always at minimum 'awareness'. "
                    "Reserve 'inert' for epi surveys, preclinical-only findings, or results "
                    "with no conceivable treatment or management implication. "
                    "Err toward 'awareness' when uncertain."
                ),
            },

            # ── Signal classification (signal-centric architecture) ───────────
            # The unit of output is an OncologySignal, not a paper. This field
            # classifies the *type* of signal this evidence source contributes.
            # Used by tier_logic.py and the signal clustering layer.
            "signal_type": {
                "type": "string",
                "enum": [
                    "FDA_APPROVAL",               # FDA approval or label change
                    "GUIDELINE_UPDATE",            # NCCN/ASCO/ESMO/ASTRO formal revision
                    "PHASE_III_POSITIVE",          # Phase III RCT with positive primary result
                    "PHASE_III_NEGATIVE",          # Phase III RCT that failed primary endpoint
                    "PRACTICE_CHANGING_PHASE_II",  # Phase II with regulatory/high-need signal
                    "LATE_BREAKING_ABSTRACT",      # ASCO/ESMO/ASTRO LBA or plenary
                    "SAFETY_SIGNAL",               # Major toxicity or label safety update
                    "BIOMARKER_SIGNAL",            # Biomarker-defined result with clinical impact
                    "RADONC_TECHNIQUE",            # Radiation dose/field/fractionation change
                    "DE_ESCALATION",               # Noninferiority or de-escalation result
                    "OTHER",                       # Other practice-relevant signal
                ],
                "description": (
                    "The type of oncology signal this evidence source represents. "
                    "Classify based on what the result IS, not just where it was published. "
                    "An FDA_APPROVAL is classified as such even if you learned it from a PubMed abstract. "
                    "A PHASE_III_POSITIVE requires the primary endpoint to have been met. "
                    "A PHASE_III_NEGATIVE means the Phase III trial failed its primary endpoint. "
                    "DE_ESCALATION is for randomized noninferiority or omission trials. "
                    "BIOMARKER_SIGNAL for results defined by a biomarker (EGFR, MSI-H, BRCA, etc.) "
                    "that directly changes treatment selection. "
                    "LATE_BREAKING_ABSTRACT for LBA/plenary abstracts without a full publication yet."
                ),
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
            # Structured extraction fields (deterministic tier computation)
            "study_phase",
            "primary_endpoint_type",
            "primary_endpoint_met",
            "effect_direction",
            "hr_value",
            "p_value_significant",
            "hard_to_treat",
            # Judgment fields
            "why_it_matters",
            "who_should_care",
            "limitations_flags",
            "regimen_description",
            "carcinos_one_liner",
            "evidence_quotes",
            "why_it_surfaced",
            "radiation_oncology_relevance",
            "confidence",
            "reject_recommendation",
            "trial_name",
            "signal_type",
            "elevates_to_practice_changing",
            "clinical_actionability",
        ],
    },
}
