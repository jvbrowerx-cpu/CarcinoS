"""Genitourinary — prostate, bladder/urothelial, kidney/RCC, testis, penile."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="gu",
    name="Genitourinary",
    free_text_core=(
        "prostate cancer", "prostatic carcinoma",
        "mCRPC", "castration-resistant prostate", "metastatic hormone-sensitive",
        "mHSPC", "biochemical recurrence",
        "bladder cancer", "urothelial carcinoma", "urothelial cancer",
        "muscle-invasive bladder", "MIBC",
        "non-muscle-invasive bladder", "NMIBC",
        "upper tract urothelial", "UTUC", "ureter cancer",
        "renal cell carcinoma", "RCC",
        "kidney cancer", "renal cancer",
        "clear cell RCC", "papillary RCC", "chromophobe",
        "testicular cancer", "germ cell tumor", "seminoma", "non-seminoma",
        "penile cancer", "penile squamous",
        "adrenocortical carcinoma",
    ),
    mesh_headings=(
        "Prostatic Neoplasms",
        "Urinary Bladder Neoplasms",
        "Carcinoma, Renal Cell",
        "Kidney Neoplasms",
        "Testicular Neoplasms",
        "Urologic Neoplasms",
        "Urethral Neoplasms",
        "Penile Neoplasms",
        "Adrenal Cortex Neoplasms",
    ),
    modality_terms=(
        # Prostate hormonal / advanced
        "ADT", "androgen deprivation",
        "enzalutamide", "abiraterone", "apalutamide", "darolutamide",
        "leuprolide", "degarelix", "relugolix",
        "lutetium", "PSMA", "177Lu-PSMA", "177Lu-PSMA-617",
        "Pluvicto",
        "talazoparib", "olaparib", "niraparib", "rucaparib", "PARP",
        "docetaxel", "cabazitaxel",
        "sipuleucel-T",
        # Urothelial
        "BCG", "bacillus Calmette-Guerin",
        "enfortumab vedotin", "EV", "sacituzumab govitecan",
        "erdafitinib", "FGFR",
        "pembrolizumab", "nivolumab", "atezolizumab", "avelumab",
        "durvalumab", "tremelimumab",
        "gemcitabine", "cisplatin", "carboplatin",
        "trimodality", "bladder preservation",
        # RCC
        "cabozantinib", "sunitinib", "axitinib", "lenvatinib",
        "tivozanib", "pazopanib", "everolimus",
        "ipilimumab", "nivolumab", "pembrolizumab",
        "belzutifan", "HIF-2", "HIF-2α",
        # Surgery
        "prostatectomy", "radical prostatectomy",
        "cystectomy", "radical cystectomy",
        "nephrectomy", "partial nephrectomy",
        "orchiectomy", "RPLND",
        # Radiation
        "radiation", "radiotherapy", "IMRT",
        "brachytherapy", "low dose rate", "high dose rate", "HDR",
        "SBRT", "stereotactic", "ultra-hypofractionation",
        "MR-guided", "MRgRT",
        "proton",
        # Biomarkers
        "PSA", "PSMA PET", "DDR mutations", "BRCA",
        "ctDNA", "MRD",
    ),
    site_journals=(
        "European Urology",
        "Journal of Urology",
        "Urologic Oncology",
        "BJU International",
        "International Journal of Radiation Oncology Biology Physics",
        "Prostate Cancer and Prostatic Diseases",
    ),
)
