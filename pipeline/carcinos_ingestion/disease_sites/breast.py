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
)
