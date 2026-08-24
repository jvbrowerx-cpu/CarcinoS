"""
Pass 2 — deep review (spec §3 Pass 2).

Runs only on candidates that pass Gate 2 signal scoring. The LLM is used
ONLY for structured fact extraction — it never scores or assigns tiers.

Architecture:
  1. LLM extracts structured fields: study_phase, primary_endpoint_type,
     primary_endpoint_met, effect_direction, hr_value, p_value_significant,
     hard_to_treat, reject_recommendation, and narrative fields.
  2. compute_tier() in tier_logic.py converts those facts + qualifying_signal
     into a deterministic tier (A / B / C / NOISE). No LLM scoring involved.
  3. reject_recommendation=true is the LLM's one judgment call — it overrides
     the tier to NOISE for papers that passed the gate but are clearly noise.
"""

from __future__ import annotations
from dataclasses import dataclass

from .openai_client import OpenAIClient
from .schemas import PASS2_SCHEMA, GUIDELINE_SCHEMA
from .tier_logic import compute_tier, tier_rationale
from ..normalize.canonical import CanonicalCandidate


PASS2_SYSTEM = """You are CarcinoS Deep Review — a clinical data extraction engine.

Your ONLY jobs are:
  (1) Extract key facts from the provided text. Never add facts not in the source.
  (2) Fill the structured extraction fields accurately (study_phase, endpoint type,
      whether the endpoint was met, effect direction, HR, p-value significance, etc.)
      Tier assignment is computed by code from these fields — do NOT score or assign tiers.
  (3) Set reject_recommendation=true when this item is noise despite passing the gate.
      This is your one judgment call. Everything else is factual extraction.
  (4) Provide 1-3 short literal quotes from the abstract supporting key claims.
      Quotes MUST appear verbatim in the source. Do NOT paraphrase.
  (5) Fill why_it_surfaced with the strongest signal that got this paper through.
  (6) Set radiation_oncology_relevance using STRICT criteria:
      direct   = Radiation IS the primary intervention studied. This includes:
                 • External beam RT trials testing dose, fractionation, field size,
                   technique, RT vs no RT, or a concurrent RT schedule.
                   Signal type RADONC_TECHNIQUE always → direct.
                 • Radioligand / radiopharmaceutical therapy trials (lutetium-177,
                   radium-223, actinium-225, iodine-131, yttrium-90, or any
                   radiolabeled antibody/peptide) regardless of disease stage —
                   these are radiation medicine regardless of the oncologic setting.
                   Examples: Lu-177 PSMA (Pluvicto), Ra-223 (Xofigo), Lu-177
                   DOTATATE (Lutathera), any PRRT, any RLT FDA approval.
      indirect = RT is an ESTABLISHED, GUIDELINE-ENDORSED component of the CURRENT
                 STANDARD OF CARE in this EXACT disease/stage/setting (not just "sometimes
                 used"), AND this trial changes the systemic agent given WITH or AROUND
                 that RT (e.g., chemotherapy partner in definitive CRT for LAHNSCC, LACC,
                 or LARC; systemic intensification of standard chemoradiation sequences).
                 Examples of correct indirect: neoadjuvant CRT rectal cancer + new agent;
                 concurrent systemic therapy with definitive RT in cervical cancer.
      none     = Everything else. Specifically:
                 • Metastatic or advanced-stage disease treated with non-radioactive
                   systemic therapy where radiation plays NO role in the trial
                 • Adjuvant systemic therapy where RT's role is peripheral or elective
                 • Bladder, breast, GU, GI, or hematologic systemic trials not involving
                   CRT or radioligand/radiopharmaceutical therapy
                 • Any trial where radiation (external beam OR radioligand) is NOT
                   a core component of the studied regimen
                 • Hematologic malignancies (RT is rarely standard)
                 • Biomarker or targeted therapy trials with no radiation component
                 NOTE: Do NOT use none solely because a disease is metastatic.
                 Palliative RT trials (e.g., SBRT for oligometastatic disease, spine
                 SBRT, bone mets RT dose/fractionation, whole brain RT vs SRS) are
                 direct even in the metastatic setting — RT is still the intervention.
                 When in doubt, use none — over-labeling indirect dilutes the rad onc filter.
  (7) Set confidence: high / moderate / low — your confidence this belongs in the portal.

Rules:
  - Extract only what is stated in the source. Never extrapolate.
  - If a value is not reported, write "not_reported" for text fields.
  - For primary_endpoint_met: use the pre-specified primary endpoint and its
    alpha threshold. If the abstract reports p=0.034 for the primary endpoint,
    primary_endpoint_met=true. If p=0.12, primary_endpoint_met=false.
  - For hr_value: report the numeric hazard ratio (e.g. 0.76). Use null if
    no HR is reported or if the primary endpoint is not a time-to-event outcome.
  - For p_value_significant: true if p < pre-specified alpha (typically 0.05).
  - For effect_direction: report the direction of the PRIMARY result, not secondary endpoints.
  - For hard_to_treat: true for GBM, SCLC, pancreatic, biliary/cholangiocarcinoma,
    mesothelioma, gastric, DIPG, or any cancer with expected OS < 12 months in this setting.

─────────────────────────────────────────────────────────────────────────────
STRUCTURED EXTRACTION — fill these fields accurately
─────────────────────────────────────────────────────────────────────────────

study_phase — select exactly one:
  phase3_rct          Primary results of a randomized Phase III trial
  phase2_rct          Phase II trial with a randomized comparator arm
  phase2_single_arm   Phase II trial, no comparator (single-arm)
  phase1              Dose-finding or safety study
  meta_analysis       Quantitative pooled analysis or IPD meta-analysis
  systematic_review   Qualitative systematic review (no quantitative pooling)
  guideline_update    Formal revision: NCCN, ASCO, ESMO, ASTRO, ASH
  fda_approval        FDA approval record
  observational       Cohort, registry, real-world, retrospective
  other_or_unclear

CRITICAL classification rules for study_phase:
  • A paper that POOLS or SYNTHESISES Phase III trials is a meta_analysis —
    NOT phase3_rct. Key phrases: "network meta-analysis", "systematic review
    and meta-analysis", "pooled analysis of RCTs", "Bayesian network
    meta-analysis", "IPD meta-analysis". If the paper describes pooling data
    from multiple trials, always select meta_analysis.
  • A society consensus paper or expert panel review (SNO, EANO, NCCN
    Insights, etc.) that does NOT constitute a formal NCCN / ASCO / ESMO /
    ASTRO / ASH guideline version update is systematic_review, NOT
    guideline_update. Reserve guideline_update exclusively for formal
    versioned revisions from those five bodies.
  • phase3_rct is reserved for the PRIMARY results paper of a single named
    Phase III trial (e.g. LAURA, FLAURA2, CheckMate-816). If you are unsure
    whether this is primary trial data vs. a meta-analysis, default to
    meta_analysis — the deterministic tier cap for meta-analyses is safer.

primary_endpoint_type — the PRE-SPECIFIED primary endpoint of the study:
  overall_survival / progression_free_survival / disease_free_survival /
  event_free_survival / objective_response_rate / non_inferiority /
  pathologic_response / locoregional_control / other / not_reported

primary_endpoint_met — boolean:
  true  = primary endpoint formally met at pre-defined significance threshold
  false = primary endpoint NOT met (negative trial or missed primary)

effect_direction — direction of the PRIMARY result:
  positive      intervention shows benefit (lower HR, higher ORR, longer OS)
  non_inferior  NI margin pre-specified and confirmed (de-escalation proven)
  negative      no benefit or harm demonstrated
  inconclusive  mixed or ambiguous signal
  not_reported  insufficient data in abstract

hr_value — numeric hazard ratio (e.g. 0.76) or null if not a time-to-event endpoint

p_value_significant — boolean: p < pre-specified alpha (typically 0.05)

hard_to_treat — boolean: true for GBM, SCLC, pancreatic, biliary,
  mesothelioma, gastric, DIPG, appendiceal, or any setting with expected OS < 12 months

trial_name — the canonical trial acronym or short name if this paper reports primary
  or updated results from a named clinical trial. Examples: "FLAURA2", "CheckMate-816",
  "LAURA", "PATHOS", "CHRYSALIS". Use the shortest widely-recognized name. Write null if
  this is not a named trial, is a review or meta-analysis, or the trial name cannot be
  determined. Used for cross-source deduplication — if FLAURA2 data appears in both a
  JCO article and an ASCO abstract, only the highest-priority source is kept.

─────────────────────────────────────────────────────────────────────────────
SIGNAL TYPE — classify the kind of oncology signal
─────────────────────────────────────────────────────────────────────────────
Set signal_type based on what the result IS, not where it was published:

  FDA_APPROVAL           — FDA granted approval or label change (any source)
  GUIDELINE_UPDATE       — NCCN/ASCO/ESMO/ASTRO formal version revision
  PHASE_III_POSITIVE     — Phase III RCT with primary endpoint MET, positive direction
  PHASE_III_NEGATIVE     — Phase III RCT that FAILED its primary endpoint
  PRACTICE_CHANGING_PHASE_II — Phase II with regulatory link, rare disease standard,
                            OR biomarker-defined result in high-need space with
                            compelling ORR/PFS in an area lacking alternatives
  LATE_BREAKING_ABSTRACT — ASCO/ESMO/ASTRO LBA or plenary without full publication
  SAFETY_SIGNAL          — Major new toxicity finding or label safety update
  BIOMARKER_SIGNAL       — Biomarker-directed result that changes patient selection
                            (e.g. MSI-H, BRCA, TMB, EGFR exon 20, HER2 IHC 3+)
  RADONC_TECHNIQUE       — Randomized trial directly changing RT dose/field/fractionation
  DE_ESCALATION          — Randomized noninferiority or omission trial
  OTHER                  — Practice-relevant but doesn't fit above categories

─────────────────────────────────────────────────────────────────────────────
NEGATIVE TRIAL AND SAFETY SIGNAL ELEVATION
─────────────────────────────────────────────────────────────────────────────
Set elevates_to_practice_changing=true ONLY when a PHASE_III_NEGATIVE or
SAFETY_SIGNAL rises to Tier A (Practice Impacting) because it forces an
immediate clinical action change — not just clarifies uncertainty.

PHASE_III_NEGATIVE → elevates_to_practice_changing=true when:
  • The trial stops adoption of a treatment that had become near-standard or
    was widely expected to become standard. Clinicians who were about to adopt
    this now should not. ("Do not use X in setting Y.")
  • The result invalidates an existing standard of care or reverses clinical
    enthusiasm at the point where change is now required.
  • The negative result directly affects guideline interpretation (e.g. NCCN
    will need to revise, or a current recommendation is now unsupported).

  elevates_to_practice_changing=false (stays Tier B) when:
  • The experimental arm was speculative, never widely adopted, and the result
    simply closes an exploratory question.
  • The result is important to know but does not change what clinicians will
    do in clinic this week.

SAFETY_SIGNAL → elevates_to_practice_changing=true when:
  • New black-box warning or drug withdrawal
  • Excess mortality finding in a trial or post-market surveillance
  • Requires immediate changes to patient selection, prescribing, monitoring,
    or consent for a widely-used drug or regimen

  elevates_to_practice_changing=false (stays Tier B) when:
  • Notable toxicity finding but already in the label or expected class effect
  • Does not require immediate clinical action beyond awareness

For all other signal_types: elevates_to_practice_changing=false always.

─────────────────────────────────────────────────────────────────────────────
REJECT RECOMMENDATION — your one judgment call
─────────────────────────────────────────────────────────────────────────────
DEFAULT IS KEEP. Set reject_recommendation=true ONLY when the paper clearly
matches one of the specific criteria below. When in doubt, keep it — a Tier C
Horizon card is better than a false rejection of a clinically relevant paper.

ALWAYS keep (reject_recommendation=false):
  • Phase III primary results — any direction, any endpoint
  • Phase II randomized with a reported primary endpoint
  • FDA approval or formal guideline update
  • Landmark meta-analyses that resolve a contested clinical question
  • Any major conference LBA/plenary abstract
  • Any paper from NEJM, Lancet, JCO, JAMA, JAMA Oncology, Annals of Oncology,
    or European Urology that reports a trial result with a numeric endpoint AND
    the study population has a malignant or premalignant diagnosis. Journal prestige
    does NOT override the non-oncology population rule below — a Phase III RCT in
    sickle cell disease patients is not oncology and must be rejected.

REJECT (reject_recommendation=true) only for these specific categories:
  • Paraneoplastic syndromes — not treatment practice-changing
  • Auto-segmentation / AI contouring / treatment planning software — physics QA
  • Prognostic biomarker / nomogram with no accompanying intervention data
  • Exploratory / post-hoc subgroup only — not ITT primary result, no predefined hypothesis
  • Single-institution retrospective, n < 50, standard regimen, no new finding
  • SEER / NCDB / claims data describing practice patterns only (no intervention comparison)
  • Surgical technique paper — "robotic learning curve", "port placement", operative steps
  • Phase III trial where HR, p-value, AND primary endpoint are all missing or uninterpretable
  • GLP-1 / SGLT2 pharmacoepidemiology — observational confounding, no direct oncology intervention
  • Non-oncology population — primary study population has no malignant or premalignant
    diagnosis. This rule overrides journal prestige and study design — even a Phase III RCT
    from NEJM or JAMA must be rejected if no patients in the study have cancer.
    Non-malignant conditions that must be rejected include:
      – Hematologic non-malignancies: sickle cell disease, sickle cell anemia, thalassemia,
        hemophilia, hereditary spherocytosis, aplastic anemia, immune thrombocytopenia (ITP),
        von Willebrand disease, hereditary hemolytic anemia. These are NOT oncology even when
        published in hematology journals alongside leukemia/lymphoma papers.
      – Dermatologic/autoimmune: vitiligo, psoriasis, atopic dermatitis, eczema, alopecia areata
      – Cardiovascular/surgical: cardiac surgery in non-cancer patients, platelet storage for
        non-oncologic surgery, heart failure without malignancy, peripheral artery disease
      – General: chronic musculoskeletal pain, diabetes, obesity, general chronic pain
    If the abstract describes a study population where all patients have a non-malignant
    primary diagnosis and no cancer-specific subgroup is analyzed, reject regardless of
    journal, phase, or study design.
  • Below-MCID result — the abstract explicitly states that the primary endpoint was met
    statistically but did NOT reach the prespecified minimal clinically important difference
    (MCID). When the trial itself reports the effect is below clinical meaningfulness
    (e.g. "did not meet the prespecified MCID", "below the threshold for clinical importance"),
    reject. A statistically significant but clinically sub-threshold result does not belong
    in CarcinoS unless a secondary endpoint of substantial clinical importance also met MCID.
  • Secondary/modeling analysis of a phase III trial — NTCP models, dosimetric analyses,
    QoL substudies, pharmacokinetic substudies, biomarker/translational sub-studies, or
    cost-effectiveness analyses that DERIVE from a phase III trial but are NOT the primary
    results paper. These do not change practice on their own; they inform planning details.
    Reject unless the secondary analysis itself has a primary prospective hypothesis with
    a predefined endpoint, randomized comparator, and a clinically actionable result.
    Common identifiers: "NTCP model", "secondary analysis of [TRIAL NAME]", "dosimetric
    analysis", "subgroup analysis of the [TRIAL NAME] trial", "translational analysis".

─────────────────────────────────────────────────────────────────────────────
EVIDENCE STRENGTH — for display and sanity-check only (does not determine tier)
─────────────────────────────────────────────────────────────────────────────
  A = Phase III RCT primary results / FDA approval / major guideline update
  B = Phase II randomized / landmark meta-analysis / Phase III strong but not primary
  C = Phase II single-arm / meta-analysis of unsettled question / emerging signal
  D = Anything else

─────────────────────────────────────────────────────────────────────────────
CALIBRATION RULES — strictly enforced to prevent systematic over-elevation
─────────────────────────────────────────────────────────────────────────────

1. FORBIDDEN PHRASES IN carcinos_one_liner
   Never write any of the following unless study_phase=fda_approval OR
   study_phase=guideline_update:
     • "new standard of care"
     • "potential new standard"
     • "supports consideration as" (when referring to standard-of-care status)
     • "establishes a new standard"
   These phrases overstate certainty for non-regulatory results. Instead write
   what the result achieved factually: "improves PFS", "met its primary endpoint",
   "demonstrated OS benefit".

2. EVIDENCE GRADE — nonrandomized data does NOT inherit Phase III evidence grade
   A paper embedded in a Phase III program that is itself nonrandomized
   (patient-reported outcomes substudy, translational sub-study, cohort analysis
   within a Phase III) must be classified as observational, NOT phase3_rct.
   The evidence grade it receives should reflect the actual study design of the
   paper at hand, not the parent trial. Only the primary results paper of a
   named Phase III RCT qualifies for phase3_rct.

3. HORIZON FLOOR — single-arm Phase II without comparator defaults to Tier C
   Set study_phase=phase2_single_arm for any Phase II that lacks a randomized
   comparator arm. Favorable response rates (ORR, PFS, OS) in a single-arm study
   do NOT justify classification as phase2_rct or elevation above Tier C
   without external validation. The absence of a comparator is the defining
   characteristic — not the result direction.

4. SECONDARY ANALYSIS CLASSIFICATION — does NOT inherit Phase III status
   A modeling study, NTCP analysis, toxicity sub-study, quality-of-life substudy,
   translational or biomarker substudy, cost-effectiveness analysis, or pharmacokinetic
   substudy that DERIVES from a phase III trial but is NOT the primary results paper
   MUST be classified as observational, NOT phase3_rct.
   The fact that the parent trial was Phase III does not promote the secondary paper.
   Only the primary results paper of a named Phase III RCT (reporting the primary
   endpoint with randomized comparison) qualifies for phase3_rct.
   Common identifiers: "secondary analysis of", "NTCP model", "dosimetric analysis",
   "QoL substudy", "biomarker analysis", "post-hoc modeling", "translational analysis".

5. GUIDELINE CLASSIFICATION — formal versioned revision only
   Set study_phase=guideline_update ONLY for primary versioned guideline
   documents from these bodies: NCCN, ASCO, ESMO, ASTRO, ASH, EAU.
   Do NOT set guideline_update for:
     • Journal summaries or commentaries on existing guidelines
     • Expert consensus statements or society position papers
     • NCCN Insights articles (commentary, not a versioned revision)
     • "Summary of changes" overview articles
   If uncertain whether a paper constitutes a formal guideline revision vs. a
   commentary, classify as systematic_review.

─────────────────────────────────────────────────────────────────────────────
TEXT QUALITY RULES — strictly enforced
─────────────────────────────────────────────────────────────────────────────
Every text field must be publication-ready. No lowercase sentence starts.
No telegraphic fragments. Write as a clinical editor would.

  population
    Complete noun phrase starting with the patient type. Include age range,
    performance status, and key eligibility criteria.
    ✓ "Resected locally advanced SCCHN (oral cavity/oropharynx/larynx/
       hypopharynx), age 19–74, ECOG 0–1, ≥1 high-risk pathologic feature
       (e.g., ENE, positive margin, ≥4 nodes without ENE, PNI)."
    ✗ "patients with resected SCCHN"

  regimen_description
    Proper-case narrative. Include study design, arms, doses, and schedule
    where reported.
    ✓ "Open-label phase III; cisplatin + PORT (66 Gy, cisplatin 100 mg/m²
       q3w ×3) vs same backbone + nivolumab (peri-CRT + adjuvant schedule)."
    ✗ "phase 3 trial nivolumab vs placebo"

  key_results.effect_size
    Complete finding sentence including the endpoint name, direction, and
    numeric result. Include HR/OR/ORR and CI in the same field.
    ✓ "DFS improved with nivolumab + cisplatin-RT vs cisplatin-RT alone
       (HR 0.76, 95% CI 0.60–0.98; p=0.034), regardless of PD-L1 status."
    ✗ "DFS HR 0.76"

  key_results.toxicity_qol_signal
    Complete sentence starting with a capital letter.
    ✓ "Higher grade 4 treatment-related AEs with nivolumab arm (10% vs 5%);
       treatment-related deaths: 2 in each group."
    ✗ "more toxicity in nivo arm"

  carcinos_one_liner
    One complete sentence. Starts with capital. States the clinical
    implication clearly for a radiation or medical oncologist.
    ✓ "For high-risk resected LA-SCCHN, adding nivolumab to standard
       postoperative cisplatin-RT meaningfully improves DFS with a moderate
       toxicity increase, supporting its incorporation into adjuvant regimens."
    ✗ "nivolumab improves DFS in SCCHN"

Output MUST be valid JSON matching the schema. No prose. No extra keys.
"""


PASS2_USER_TEMPLATE = """Deep-review this {site_name} oncology candidate.

CANDIDATE:
- title: {title}
- abstract: {abstract}
- journal: {journal}
- publication_date: {publication_date}
- publication_types: {publication_types}
- mesh_terms: {mesh_terms}
- modality_keywords_present: {modality_keywords_present}
- pmid: {pmid}
- doi: {doi}
- nct_ids: {nct_ids}

SIGNAL GATE CONTEXT (why the deterministic gate kept this paper):
- signal_score: {pass1_score}
- priority_hint: {pass1_hint}
- gate_signals: {pass1_one_liner}
- gate_signal_type_hint: {gate_signal_type}

INSTRUCTIONS:
1. Set signal_type based on what the result IS (see system prompt). The
   gate_signal_type_hint above is a suggestion from the deterministic gate —
   override it if the abstract makes the true signal type clearer.

2. DEFAULT IS KEEP — set reject_recommendation=true ONLY if this paper
   clearly matches one of the specific reject categories in the system prompt
   (e.g. single-institution retrospective n<50, SEER/NCDB patterns-only,
   surgical technique, prognostic biomarker with no intervention, AI
   contouring, GLP-1 pharmacoepidemiology). When in doubt, keep it.

3. Use why_it_surfaced to record the strongest clinical justification.
   If rejecting, cite the specific reject category from the system prompt.

Return JSON only.
"""


@dataclass
class Pass2Result:
    parsed: dict
    evidence_strength: str
    final_tier_code: str   # 'A' / 'B' / 'C' / 'NOISE' — maps to alerts.tier in schema
    tier_rationale_text: str
    notify: bool
    cost_usd_estimate: float


def run_pass2(
    client: OpenAIClient,
    candidate: CanonicalCandidate,
    pass1_parsed: dict,
    qualifying_signal: str = "",
    model: str | None = None,
) -> Pass2Result:
    # Map qualifying_signal → signal_type hint for the LLM prompt
    from ..signal import QS_TO_SIGNAL_TYPE
    gate_signal_type = QS_TO_SIGNAL_TYPE.get(qualifying_signal, "OTHER")

    user = PASS2_USER_TEMPLATE.format(
        site_name=candidate.cancer_site_name,
        title=candidate.title or "(no title)",
        abstract=(candidate.abstract or "")[:8000] or "(no abstract)",
        journal=candidate.journal or "(unknown)",
        publication_date=candidate.publication_date or "(unknown)",
        publication_types=", ".join(candidate.publication_types) or "(none)",
        mesh_terms=", ".join(candidate.mesh_terms[:20]) or "(none)",
        modality_keywords_present=", ".join(candidate.modality_keywords_present) or "(none)",
        pmid=candidate.pmid,
        doi=candidate.doi or "(none)",
        nct_ids=", ".join(candidate.nct_ids) or "(none)",
        pass1_score=pass1_parsed.get("relevance_score"),
        pass1_hint=pass1_parsed.get("priority_hint"),
        pass1_one_liner=pass1_parsed.get("one_line_rationale", "")[:200],
        gate_signal_type=gate_signal_type,
    )

    result = client.structured(
        model=model or client.deep_review_model,
        system=PASS2_SYSTEM,
        user=user,
        schema=PASS2_SCHEMA,
        temperature=0.0,
    )
    parsed = result.parsed

    evidence = str(parsed.get("evidence_strength", "D"))

    # Deterministic tier assignment — no LLM scoring involved.
    # compute_tier() reads structured extraction fields from the LLM response
    # and applies fixed rules. The only LLM judgment is reject_recommendation.
    final_code = compute_tier(parsed, qualifying_signal)
    rationale_text = tier_rationale(parsed, qualifying_signal, final_code)

    notify = decide_notify(final_code, parsed)
    cost = _estimate_pass2_cost(result.usage, model=model or client.deep_review_model)

    return Pass2Result(
        parsed=parsed,
        evidence_strength=evidence,
        final_tier_code=final_code,
        tier_rationale_text=rationale_text,
        notify=notify,
        cost_usd_estimate=cost,
    )


# ---------------------------------------------------------------------------
# DEPRECATED — enforce_tier_mapping() removed in deterministic-tier refactor.
# Tier assignment is now handled by compute_tier() in triage/tier_logic.py.
# The LLM no longer scores papers; it only extracts structured facts.
# ---------------------------------------------------------------------------


def decide_notify(tier: str, parsed: dict) -> bool:
    """
    Spec §8.2: Tier C never notifies.
    Spec §5.2: conflicts block notify (handled at persistence layer).
    """
    if tier in ("A", "B"):
        return True
    return False


def _estimate_pass2_cost(usage: dict, model: str = "") -> float:
    """
    Token-based cost estimate using published OpenAI rates.
    Rates are model-aware so the figure in pipeline_runs reflects reality.
    These are for budget telemetry only — do not use for billing.
    """
    m = model.lower()
    if "gpt-4o-mini" in m:
        in_per_million, out_per_million = 0.15, 0.60
    elif "gpt-4o" in m:
        in_per_million, out_per_million = 2.50, 10.00
    elif "gpt-4.1-mini" in m:
        in_per_million, out_per_million = 0.40, 1.60
    elif "gpt-4.1" in m:
        in_per_million, out_per_million = 2.00, 8.00
    else:
        # Unknown / future model — use gpt-4o rates as a conservative estimate
        in_per_million, out_per_million = 2.50, 10.00
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    return (pt / 1e6) * in_per_million + (ct / 1e6) * out_per_million


# ---------------------------------------------------------------------------
# Quote-grounding check (anti-hallucination)
# ---------------------------------------------------------------------------

PASS2_GUIDELINE_SYSTEM = """You are CarcinoS Guideline Extraction — a specialist engine for formal clinical guideline documents.

Your ONLY job is to extract WHAT CHANGED in this guideline update: the specific
recommendation changes (previous → new), who issued them, and which clinicians
must act on them.

Do NOT extract HR values, p-values, ORR, or trial results — this is a guideline
document, not a trial. The clinical value is the recommendation change itself.

─────────────────────────────────────────────────────────────────────────────
WHAT TO EXTRACT
─────────────────────────────────────────────────────────────────────────────

guideline_body
  The issuing organisation. Use the shortest widely-recognised abbreviation:
  NCCN, ASCO, ESMO, ASTRO, ASH, EAU, SNO, EANO, etc.

guideline_version_or_year
  The version or year of THIS document: "v2.2026", "2026 Update", "Version 3.2026".

disease_area
  Disease area and setting. Be specific: "BCG-unresponsive high-risk NMIBC",
  "Resectable NSCLC — neoadjuvant and perioperative", "Relapsed/refractory DLBCL".

recommendation_changes (up to 3 most important)
  For each changed recommendation:
    previous: What was previously recommended (or "New recommendation — not
              previously addressed" if this section is newly added).
    new:      The updated recommendation, stated precisely. Include drug names,
              doses/schedules, and indication if mentioned.
    strength: Strength-of-recommendation as stated: "Category 1", "Strong",
              "Grade A", "Conditional", "GRADE 2B". Null if not reported.
    who_should_change: The specific clinician type most affected. Be concrete:
              "Urologists managing BCG-unresponsive NMIBC", "Medical oncologists
              treating first-line metastatic NSCLC with EGFR exon 20 insertion".

evidence_strength
  A = formal versioned guideline update from a major body (NCCN/ASCO/ESMO/
      ASTRO/ASH/EAU) with clearly changed recommendations.
  B = expert consensus with concrete practice guidance but not a formal
      versioned revision.
  C = informal summary, commentary, or review of an existing guideline.
  D = unclear or insufficient — cannot determine what changed.

carcinos_one_liner
  One complete sentence. Format:
  "[Guideline body] [version/year] [disease area] guidelines now [specific change],
  [clinical implication]."
  Example: "The 2026 EAU NMIBC guidelines now recommend pembrolizumab as a
  Category 1 option for BCG-unresponsive high-risk NMIBC, providing the first
  guideline-endorsed alternative to radical cystectomy in this setting."
  FORBIDDEN: "new standard of care", "supports consideration", "potential new standard".

who_should_care
  Select 1–4 clinician roles most affected by these changes.

radiation_oncology_relevance
  direct   = RT is the primary intervention: the guideline changes RT dose,
             field, fractionation, technique, or RT vs no RT recommendation
  indirect = RT is ESTABLISHED standard of care in this exact disease/stage
             AND this guideline changes the systemic agent given WITH or AROUND
             that RT (e.g., chemotherapy partner in definitive CRT for LAHNSCC,
             LACC, or LARC; systemic intensification of chemoradiation sequences)
  none     = systemic/surgical/targeted guideline in a setting where RT is not
             a core component; hematologic malignancies; metastatic disease;
             biomarker or targeted therapy guidelines. Default to none when
             uncertain — do not over-label as indirect.

reject_recommendation
  Set true if:
    • This is a JOURNAL SUMMARY, COMMENTARY, or REVIEW of a guideline rather
      than the primary guideline document itself.
    • No concrete recommendation changes can be extracted (only general overviews).
    • The paper describes guideline methodology or history rather than specific
      clinical recommendations that changed.
  Set false for primary versioned guideline documents with extractable changes.

why_it_surfaced
  Brief note on why this guideline document passed the signal gate.

confidence
  high     = primary versioned document with clear recommendation changes
  moderate = formal guideline but changes are ambiguous or minor
  low      = unclear whether this is a primary document or a summary

─────────────────────────────────────────────────────────────────────────────
QUALITY RULES
─────────────────────────────────────────────────────────────────────────────
  • "previous" and "new" must be actionable statements, not vague summaries.
    ✓ "previous: Observation or BCG recommended for intermediate-risk NMIBC"
    ✓ "new: Pembrolizumab added as Category 1 alternative to BCG for intermediate-
           and high-risk BCG-naïve NMIBC following Phase III data"
    ✗ "previous: prior guidance", "new: updated guidance"
  • All text fields must start with a capital letter and be publication-ready.
  • Return JSON only — no prose, no extra keys.
"""


PASS2_GUIDELINE_USER_TEMPLATE = """Extract guideline recommendation changes from this document.

CANDIDATE:
- title: {title}
- abstract: {abstract}
- journal: {journal}
- publication_date: {publication_date}
- publication_types: {publication_types}
- mesh_terms: {mesh_terms}
- pmid: {pmid}
- doi: {doi}

GATE CONTEXT:
- gate_signal_type_hint: {gate_signal_type}
- signal_score: {pass1_score}
- gate_one_liner: {pass1_one_liner}

INSTRUCTIONS:
1. Extract the 1–3 most clinically important RECOMMENDATION CHANGES in this document.
2. For each change, identify what was previously recommended and what the new
   recommendation is — stated precisely enough that a clinician can act on it.
3. Set reject_recommendation=true if this is a summary/commentary rather than
   the primary guideline document, or if no concrete changes are extractable.
4. Do NOT report HR, p-values, or ORR — this is a guideline document, not a trial.

Return JSON only.
"""


def _enrich_guideline_via_web(
    client: OpenAIClient,
    title: str,
    pub_date: str,
    guideline_body: str = "",
    disease_area: str = "",
) -> list[dict]:
    """
    When a guideline abstract is too vague to extract concrete recommendation
    changes, use a web search to find what actually changed in this update.

    Returns a list of recommendation_change dicts (matching GUIDELINE_SCHEMA),
    or [] if nothing concrete can be found or web search is unavailable.
    """
    import re
    import logging
    log = logging.getLogger("carcinos.pipeline")

    body_hint = f" ({guideline_body})" if guideline_body else ""
    disease_hint = f" for {disease_area}" if disease_area else ""

    prompt = (
        f"I need to know what SPECIFICALLY changed in this clinical oncology "
        f"guideline update{disease_hint}:\n\n"
        f"Title: {title}\n"
        f"Publication date: {pub_date}\n"
        f"Guideline body: {guideline_body or 'unknown'}\n\n"
        f"Search the official society website{body_hint} and any news coverage "
        f"to find the SPECIFIC recommendation changes in this version update. "
        f"I need to know: what was the previous recommendation, and what is the "
        f"new recommendation?\n\n"
        f"For each concrete recommendation change you find, output EXACTLY:\n"
        f"SETTING: [clinical setting, e.g. 'First-line advanced NSCLC']\n"
        f"PREVIOUS: [previous recommendation, quoted or paraphrased precisely]\n"
        f"NEW: [new recommendation, quoted or paraphrased precisely]\n\n"
        f"Rules:\n"
        f"- Only include changes that are ACTIONABLE (a clinician can do something different)\n"
        f"- Do NOT include vague statements like 'recommendations were updated'\n"
        f"- If you cannot find any specific recommendation changes, output: NO_CHANGES_FOUND\n"
        f"- Output at most 3 changes (the most clinically important ones)"
    )

    raw = client.web_search(prompt)
    if not raw or "NO_CHANGES_FOUND" in raw:
        return []

    # Parse SETTING/PREVIOUS/NEW blocks
    _BLANK = {None, "", "not_reported", "Not applicable", "N/A", "n/a",
              "not applicable", "None", "unknown"}

    changes = []
    blocks = re.findall(
        r"SETTING:\s*(.+?)\s*\nPREVIOUS:\s*(.+?)\s*\nNEW:\s*(.+?)(?=\nSETTING:|\Z)",
        raw,
        re.DOTALL,
    )
    for setting, previous, new in blocks:
        setting  = setting.strip()
        previous = previous.strip()
        new      = new.strip()
        if new and new not in _BLANK and len(new) > 10:
            changes.append({
                "setting":         setting,
                "previous":        previous,
                "new":             new,
                "drug":            "",
                "evidence_cited":  "",
            })

    if not changes:
        log.debug(
            "guideline web enrichment: response had content but no parseable "
            "SETTING/PREVIOUS/NEW blocks — raw[:300]: %s", raw[:300]
        )
    return changes


def run_pass2_guideline(
    client: OpenAIClient,
    candidate: CanonicalCandidate,
    pass1_parsed: dict,
    qualifying_signal: str = "",
    model: str | None = None,
) -> Pass2Result:
    """
    Dedicated extraction path for GUIDELINE documents.
    Uses GUIDELINE_SCHEMA and PASS2_GUIDELINE_SYSTEM instead of the
    trial-centric PASS2_SCHEMA and PASS2_SYSTEM.
    Called by pipeline._do_pass2() when qualifying_signal == 'GUIDELINE'.
    """
    from ..signal import QS_TO_SIGNAL_TYPE
    gate_signal_type = QS_TO_SIGNAL_TYPE.get(qualifying_signal, "GUIDELINE_UPDATE")

    user = PASS2_GUIDELINE_USER_TEMPLATE.format(
        title=candidate.title or "(no title)",
        abstract=(candidate.abstract or "")[:8000] or "(no abstract)",
        journal=candidate.journal or "(unknown)",
        publication_date=candidate.publication_date or "(unknown)",
        publication_types=", ".join(candidate.publication_types) or "(none)",
        mesh_terms=", ".join(candidate.mesh_terms[:20]) or "(none)",
        pmid=candidate.pmid,
        doi=candidate.doi or "(none)",
        gate_signal_type=gate_signal_type,
        pass1_score=pass1_parsed.get("relevance_score"),
        pass1_one_liner=pass1_parsed.get("one_line_rationale", "")[:200],
    )

    result = client.structured(
        model=model or client.deep_review_model,
        system=PASS2_GUIDELINE_SYSTEM,
        user=user,
        schema=GUIDELINE_SCHEMA,
        temperature=0.0,
    )
    parsed = result.parsed

    evidence = str(parsed.get("evidence_strength", "D"))

    # Code-level quality gate: if no concrete recommendation changes were
    # extractable, force NOISE regardless of evidence_strength.
    # This fires when the abstract doesn't list specific changes (e.g. ASCO
    # Living Guidelines whose JCO abstract says only "updated recommendations").
    # The LLM correctly returns empty/not-applicable entries but may not set
    # reject_recommendation=true because the document IS a primary guideline.
    if not parsed.get("reject_recommendation", False):
        rec_changes = parsed.get("recommendation_changes") or []
        _BLANK_VALUES = {None, "", "not_reported", "Not applicable",
                         "N/A", "n/a", "not applicable", "None"}
        has_concrete_change = any(
            c.get("new") not in _BLANK_VALUES
            for c in rec_changes
        )
        if not has_concrete_change:
            import logging as _logging
            _log = _logging.getLogger("carcinos.pipeline")
            _log.info(
                "guideline pass2: abstract has no concrete changes — "
                "attempting web search enrichment (title: %s)",
                candidate.title[:80],
            )
            # The abstract alone can't tell us what's new in a living guideline.
            # Try a targeted web search to find the actual recommendation changes
            # before giving up and dropping the card.
            web_changes = _enrich_guideline_via_web(
                client=client,
                title=candidate.title or "",
                pub_date=candidate.publication_date or "",
                guideline_body=parsed.get("guideline_body", ""),
                disease_area=parsed.get("disease_area", ""),
            )
            if web_changes:
                parsed["recommendation_changes"] = web_changes
                parsed["reject_recommendation"] = False
                # Mark the one-liner so the editor knows the content came from
                # web search, not the abstract.
                parsed["why_it_surfaced"] = (
                    (parsed.get("why_it_surfaced") or "")
                    + " [changes sourced via web search — abstract was non-specific]"
                ).strip()
                _log.info(
                    "guideline pass2: web enrichment found %d concrete change(s) "
                    "for '%s'",
                    len(web_changes), candidate.title[:60],
                )
            else:
                parsed["reject_recommendation"] = True
                evidence = "D"
                _log.info(
                    "guideline pass2: web enrichment also found no concrete changes — "
                    "dropping as NOISE (title: %s)",
                    candidate.title[:80],
                )

    # Guideline tier assignment:
    # Living guidelines update frequently with minor wording changes that are
    # rarely clinically actionable on their own — the underlying trial driving
    # any major change is almost always captured by the PubMed lane separately.
    # To avoid noise, only evidence_strength A (concrete practice-changing
    # recommendation) survives. B/C guideline updates are dropped as NOISE.
    # This means CarcinoS only surfaces a guideline card when something
    # genuinely practice-impacting changed (e.g. a new Category 1 drug added).
    if parsed.get("reject_recommendation", False):
        final_code = "NOISE"
    elif evidence == "A":
        final_code = "A"
    else:
        # B, C, D — drop. The underlying trial is likely already in the queue.
        final_code = "NOISE"

    # Build a synthetic tier_rationale_text for admin audit log
    body = parsed.get("guideline_body", "")
    version = parsed.get("guideline_version_or_year", "")
    disease = parsed.get("disease_area", "")
    rationale_text = (
        f"Tier {final_code} — GUIDELINE extraction: {body} {version}, {disease}. "
        f"evidence_strength={evidence}, "
        f"reject={parsed.get('reject_recommendation', False)}, "
        f"confidence={parsed.get('confidence', 'unknown')}"
    )

    notify = final_code in ("A", "B")
    cost = _estimate_pass2_cost(result.usage, model=model or client.deep_review_model)

    return Pass2Result(
        parsed=parsed,
        evidence_strength=evidence,
        final_tier_code=final_code,
        tier_rationale_text=rationale_text,
        notify=notify,
        cost_usd_estimate=cost,
    )


def verify_evidence_quotes(parsed: dict, abstract: str) -> tuple[bool, list[str]]:
    """
    Verify every evidence_quote actually appears in the source abstract.
    Use a normalized substring match (whitespace-collapsed, case-insensitive).
    Returns (all_verified, list_of_unverified_quotes).
    """
    if not abstract:
        # No abstract available — quotes can't be verified, treat as ungrounded.
        return False, list(parsed.get("evidence_quotes") or [])

    haystack = " ".join(abstract.lower().split())
    unverified: list[str] = []
    for q in parsed.get("evidence_quotes") or []:
        needle = " ".join(q.lower().split())
        if not needle or needle not in haystack:
            unverified.append(q)
    return (len(unverified) == 0), unverified
