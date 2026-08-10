"""Breast — invasive, in situ, HER2/HR/TNBC subtypes."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="breast",
    name="Breast",
    free_text_core=(
        "breast cancer", "breast carcinoma",
        "ductal carcinoma in situ", "DCIS", "LCIS",
        "invasive ductal", "invasive lobular",
        "inflammatory breast",
        "triple negative breast", "triple-negative breast", "TNBC",
        "HER2-positive", "HER2 positive", "HER2-low", "HER2-zero",
        "ER-positive", "estrogen receptor", "hormone receptor",
        "BRCA", "Paget disease",
    ),
    mesh_headings=(
        "Breast Neoplasms",
        "Carcinoma, Ductal, Breast",
        "Carcinoma, Lobular",
        "Carcinoma, Intraductal, Noninfiltrating",
        "Triple Negative Breast Neoplasms",
        "Inflammatory Breast Neoplasms",
        "Paget's Disease, Mammary",
    ),
    modality_terms=(
        # Endocrine
        "endocrine therapy", "tamoxifen", "aromatase inhibitor",
        "letrozole", "anastrozole", "exemestane",
        "fulvestrant", "elacestrant", "SERD",
        "ovarian function suppression", "OFS",
        # CDK4/6
        "abemaciclib", "palbociclib", "ribociclib", "CDK4/6",
        # HER2
        "trastuzumab", "pertuzumab", "T-DM1", "ado-trastuzumab",
        "trastuzumab deruxtecan", "T-DXd", "lapatinib", "tucatinib",
        "neratinib", "margetuximab",
        # TNBC / ADC
        "sacituzumab", "datopotamab",
        # PARP / PI3K / AKT
        "olaparib", "talazoparib", "PARP",
        "alpelisib", "capivasertib", "everolimus",
        # IO
        "pembrolizumab", "atezolizumab", "checkpoint", "PD-1", "PD-L1",
        # Chemo
        "chemotherapy", "anthracycline", "doxorubicin", "epirubicin",
        "cyclophosphamide", "taxane", "paclitaxel", "docetaxel",
        "capecitabine", "carboplatin", "platinum", "eribulin",
        # Surgery
        "mastectomy", "lumpectomy", "breast-conserving",
        "axillary lymph node dissection", "sentinel lymph node",
        "oncoplastic", "reconstruction",
        # Radiation
        "radiation", "radiotherapy", "whole breast", "partial breast",
        "hypofractionation", "boost", "regional nodal irradiation",
        "post-mastectomy radiotherapy", "PMRT", "proton",
        # Screening / genetics
        "screening", "mammography", "tomosynthesis",
        "BRCA1", "BRCA2", "germline",
        # Biomarkers
        "Oncotype", "MammaPrint", "Recurrence Score", "ctDNA",
        "ESR1", "PIK3CA", "AKT1", "PTEN",
    ),
    site_journals=(
        "Breast Cancer Research and Treatment",
        "The Breast",
        "NPJ Breast Cancer",
        "Breast Cancer Research",
        "International Journal of Radiation Oncology Biology Physics",
    ),
    watched_trials=(
        # HR+ — CDK4/6i adjuvant
        "monarchE",           # Abemaciclib adjuvant HR+ HER2- high-risk
        "NATALEE",            # Ribociclib adjuvant HR+ HER2- (any risk)
        "PATINA",             # Palbociclib + anti-HER2 therapy MBC maintenance
        # HR+ — next-gen endocrine
        "EMERALD",            # Elacestrant vs ET 2L HR+ MBC ESR1-mutant
        "EMBER-3",            # Imlunestrant vs ET 2L HR+ MBC
        "EMBER-4",            # Imlunestrant adjuvant HR+ early breast cancer
        "RIGHT Choice",       # Ribociclib + ET vs chemo HR+ MBC visceral crisis
        "postMONARCH",        # Abemaciclib + fulvestrant 2L after CDK4/6i
        "MANTA",              # CDK4/6i + fulvestrant vs chemo HR+ MBC
        # HR+ — PI3K/AKT pathway
        "CAPItello-291",      # Capivasertib + fulvestrant AKT-pathway HR+ MBC
        "INAVO120",           # Inavolisib + palbociclib + fulvestrant PIK3CA MBC
        # HR+ — neoadjuvant IO
        "KEYNOTE-756",        # Pembrolizumab + chemo neoadjuvant HR+ HER2-
        # HER2+
        "DESTINY-Breast03",   # T-DXd vs T-DM1 HER2+ MBC (practice-changing)
        "DESTINY-Breast04",   # T-DXd vs chemo HER2-low MBC (landmark)
        "DESTINY-Breast06",   # T-DXd HR+ HER2-ultralow/low MBC
        "DESTINY-Breast07",   # T-DXd combinations 1L HER2+ MBC
        "DESTINY-Breast09",   # T-DXd vs THP 1L HER2+ MBC
        "KATHERINE",          # T-DM1 adjuvant HER2+ residual disease (long-term)
        "APHINITY",           # Pertuzumab + trastuzumab adjuvant HER2+ EBC (OS)
        "KAITLIN",            # CDK4/6i + anti-HER2 therapy adjuvant HER2+ EBC
        "PHERGain",           # Pertuzumab response-guided de-escalation HER2+ EBC
        "TROPION-Breast01",   # Dato-DXd vs chemo 2L HR+ HER2-low MBC
        # TNBC / BRCA
        "KEYNOTE-522",        # Pembrolizumab + chemo neoadjuvant TNBC
        "OlympiA",            # Olaparib adjuvant gBRCA+ HER2- high-risk
        "CREATE-X",           # Capecitabine adjuvant TNBC residual disease post-neoadjuvant
        "ASCENT",             # Sacituzumab govitecan vs chemo TNBC (updates)
        # Surgical / axillary
        "COMET",              # Active monitoring vs surgery DCIS
        "NSABP B-51",         # Post-mastectomy RT after pathologic node clearance
        "ALLIANCE A011202",   # ALND vs RT node-positive after neoadjuvant therapy
        # RT trials
        "FAST",               # 5-fraction whole-breast RT pilot (long-term follow-up)
        "FAST-Forward",       # 5-fraction whole-breast RT (long-term update)
        "NRG-BR007",          # NRG breast RT de-escalation trial
        "PRIMROSE",           # Post-mastectomy RT omission low-risk
        "POSITIVE",           # Endocrine therapy interruption for fertility HR+
        "DECRESCENDO",        # De-escalation RT partial breast
        "HORIZON-Breast01",   # Randomized phase III breast (watch for results)
    ),
)
