import { TierCode } from '../constants/theme';

export interface Alert {
  id: string;
  tier: TierCode;
  title: string;
  journal: string;
  phase?: string;
  disease_site: string;
  result?: string;
  one_liner: string;
  context?: string;
  key_quote?: string;
  pmid?: string;
  status: 'EXTRACTED' | 'APPROVED' | 'PUBLISHED' | 'REJECTED';
  published_at?: string;
}

// ── Published alerts (reader view) ──────────────────────────────────────────

export const DEMO_PUBLISHED: Alert[] = [
  {
    id: '1',
    tier: 'PI',
    title: 'Tarlatamab improves OS in relapsed SCLC',
    journal: 'NEJM',
    phase: 'Phase III',
    disease_site: 'Thoracic',
    result: 'OS HR 0.60 · 13.6 vs 8.3 mo',
    one_liner:
      'Tarlatamab extended overall survival vs chemotherapy in previously-treated SCLC, supporting its FDA-approved role as a standard second-line option.',
    context:
      'DeLLphi-304 randomized 573 patients with relapsed SCLC (1–2 prior lines) to tarlatamab 10 mg Q3W vs topotecan or amrubicin. Median follow-up 17 months.',
    key_quote: 'Median OS 13.6 vs 8.3 months; HR 0.60 (95% CI 0.47–0.76; p<0.0001)',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '2',
    tier: 'PI',
    title: 'Nivolumab + AVD approved in untreated cHL',
    journal: 'FDA / SWOG S1826',
    disease_site: 'Hematologic',
    result: '3-yr PFS 91% vs 82%',
    one_liner:
      'FDA approved nivolumab + doxorubicin, vinblastine, dacarbazine (N-AVD) for untreated stage III–IV classical Hodgkin lymphoma based on superior PFS over brentuximab vedotin + AVD.',
    context:
      'SWOG S1826 enrolled 994 patients aged ≥12 years. Three-year PFS 91% (N-AVD) vs 82% (BV-AVD); HR 0.48. Significant reductions in toxicity including peripheral neuropathy.',
    key_quote: '3-year PFS 91% vs 82%; HR 0.48 (95% CI 0.33–0.69)',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '3',
    tier: 'PI',
    title: 'Acalabrutinib + venetoclax all-oral approved in CLL',
    journal: 'FDA / AMPLIFY',
    disease_site: 'Hematologic',
    result: 'Practice-changing · first fixed-duration all-oral',
    one_liner:
      'FDA approved the first fixed-duration all-oral doublet for CLL: acalabrutinib + venetoclax ± obinutuzumab, providing a chemo-free time-limited regimen.',
    context:
      'AMPLIFY enrolled 867 patients with treatment-naïve CLL. Acalabrutinib + venetoclax reduced PD/death risk vs chemoimmunotherapy (HR 0.65). Treatment duration: 14 cycles.',
    key_quote: 'PFS HR 0.65 (95% CI 0.53–0.80; p<0.001) vs FCR/BR',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '4',
    tier: 'INC',
    title: 'TALAPRO-2 final OS data in mCRPC',
    journal: 'The Lancet',
    phase: 'Phase III',
    disease_site: 'GU',
    result: 'OS HR 0.80 · 45.8 vs 37.0 mo',
    one_liner:
      'Final OS analysis of TALAPRO-2: talazoparib + enzalutamide improved survival in HRR-mutant mCRPC, confirming it as a standard first-line option for biomarker-selected patients.',
    context:
      'TALAPRO-2 enrolled 805 unselected mCRPC patients; OS benefit concentrated in HRR-mutant subgroup (HR 0.66). All-comer HR 0.80 did not cross the significance boundary.',
    key_quote: 'HRR-mutant subgroup OS HR 0.66 (95% CI 0.50–0.87)',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '5',
    tier: 'INC',
    title: 'Relacorilant approved in platinum-resistant ovarian Ca',
    journal: 'FDA / ROSELLA',
    disease_site: 'Gynecologic',
    result: 'OS HR 0.65 · 16.0 vs 11.9 mo',
    one_liner:
      'Relacorilant + nab-paclitaxel received FDA approval for platinum-resistant ovarian cancer after demonstrating OS benefit in ROSELLA—the first new non-PARP agent approved in this setting in years.',
    context:
      'ROSELLA enrolled 381 patients with platinum-resistant ovarian, primary peritoneal, or fallopian tube cancer with ≥1 prior PARP inhibitor.',
    key_quote: 'Median OS 16.0 vs 11.9 months; HR 0.65 (95% CI 0.50–0.84)',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '6',
    tier: 'HOR',
    title: 'PATINA: palbociclib in HR+/HER2+ breast cancer',
    journal: 'NEJM',
    phase: 'Phase III',
    disease_site: 'Breast',
    result: 'PFS benefit · 44.3 vs 29.1 mo',
    one_liner:
      'Palbociclib added to anti-HER2 maintenance therapy improved PFS in HR+/HER2+ metastatic breast cancer — early signal that CDK4/6 inhibition may have a role beyond HR+/HER2-.',
    context:
      'PATINA enrolled 518 patients who achieved response or stable disease after 18–24 weeks of taxane + trastuzumab + pertuzumab. Median PFS 44.3 vs 29.1 mo; HR 0.74.',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '7',
    tier: 'HOR',
    title: 'Belzutifan + lenvatinib vs cabozantinib in RCC',
    journal: 'ASCO GU 2026',
    phase: 'Phase III',
    disease_site: 'GU',
    result: 'Data maturing · watch closely',
    one_liner:
      'LITESPARK-011 phase III data showed belzutifan (HIF-2α inhibitor) + lenvatinib achieved impressive ORR in previously-treated RCC; OS data immature but signal is compelling.',
    context:
      'Randomized comparison vs cabozantinib in second/third-line clear-cell RCC. ORR 52% vs 31%; median PFS 14.5 vs 9.2 months. OS crossing planned at next analysis.',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
  {
    id: '8',
    tier: 'HOR',
    title: 'Dato-DXd in EGFR-mutant NSCLC post-osimertinib',
    journal: 'JCO',
    phase: 'Phase II',
    disease_site: 'Thoracic',
    result: 'ORR 43% · DCR 84%',
    one_liner:
      'Datopotamab deruxtecan demonstrated meaningful activity after osimertinib failure in EGFR-mutant NSCLC without actionable bypass resistance — a potential chemotherapy alternative in this population.',
    context:
      'TROPION-Lung05 enrolled 152 patients with EGFR-mutant advanced NSCLC progressing on osimertinib without resistance driver mutations. Median PFS 5.4 months.',
    status: 'PUBLISHED',
    published_at: '2026-05-11',
  },
];

// ── Extracted alerts (editor/admin queue) ─────────────────────────────────

export const DEMO_EXTRACTED: Alert[] = [
  {
    id: 'e1',
    tier: 'PI',
    title: 'Osimertinib adjuvant therapy in stage IB–IIIA EGFR+ NSCLC — 5-year OS data',
    journal: 'NEJM',
    phase: 'Phase III',
    disease_site: 'Thoracic',
    result: 'OS HR 0.49 (95% CI 0.33–0.73)',
    one_liner:
      'ADAURA 5-year OS: adjuvant osimertinib halved the risk of death in resected EGFR-mutant NSCLC, cementing standard-of-care status.',
    context:
      'Updated OS from ADAURA (682 patients, stage IB–IIIA, EGFR exon 19del or L858R). 5-year OS 88% vs 78%; HR 0.49. No new safety signals.',
    key_quote: '5-year OS 88% vs 78%; HR 0.49 (95% CI 0.33–0.73; p<0.001)',
    pmid: '38902456',
    status: 'EXTRACTED',
  },
  {
    id: 'e2',
    tier: 'INC',
    title: 'Cabozantinib + atezolizumab in HCC second line',
    journal: 'JCO',
    phase: 'Phase II',
    disease_site: 'Gastrointestinal',
    result: 'ORR 26% · mPFS 6.8 mo',
    one_liner:
      'Cabo + atezo showed promising activity after sorafenib/lenvatinib failure in HCC, though OS data are immature; context needed against approved second-line options.',
    context:
      'Single-arm phase II, 71 patients with HCC after ≥1 prior systemic therapy. ORR 26%; DCR 69%; mPFS 6.8 months. Grade ≥3 AE rate 55%.',
    pmid: '38842011',
    status: 'EXTRACTED',
  },
  {
    id: 'e3',
    tier: 'HOR',
    title: 'mRNA-4157 + pembrolizumab in resected melanoma — 3-year RFS',
    journal: 'ASCO 2026',
    phase: 'Phase IIb',
    disease_site: 'Cutaneous',
    result: 'RFS HR 0.50 at 3 years',
    one_liner:
      'Personalized neoantigen mRNA vaccine (mRNA-4157) maintained durable RFS benefit at 3 years — key data point ahead of registrational phase III.',
    context:
      'V940-001 3-year update: 157 high-risk resected melanoma patients. 3-yr RFS 74.8% vs 55.6% (mRNA-4157 + pembro vs pembro alone). MNAR-05 phase III ongoing.',
    pmid: '38933120',
    status: 'EXTRACTED',
  },
  {
    id: 'e4',
    tier: 'INC',
    title: 'Zanubrutinib vs ibrutinib final OS in R/R CLL — ALPINE',
    journal: 'NEJM',
    phase: 'Phase III',
    disease_site: 'Hematologic',
    result: 'OS HR 0.79 · not yet significant',
    one_liner:
      'ALPINE final OS update: zanubrutinib numerically reduced death risk vs ibrutinib but did not meet OS significance; PFS advantage preserved. Cardiac toxicity lower with zanubrutinib.',
    context:
      '652 patients R/R CLL. Median follow-up 41 months. OS HR 0.79 (95% CI 0.58–1.08; p=0.15). PFS HR 0.65 (p<0.001). AFib/flutter 5.2% vs 13.3%.',
    pmid: '38911234',
    status: 'EXTRACTED',
  },
];

export const WEEK_LABEL = 'Week of May 11, 2026';
export const SCAN_LABEL = 'Last scan: 2h ago';
