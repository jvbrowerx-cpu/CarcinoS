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
    watched_trials=(
        # Prostate — RT + systemic intensification
        "PEACE-3",            # Radium-223 + enzalutamide mCRPC
        "ENZARAD",            # Enzalutamide + RT high-risk localized prostate
        "ATLAS",              # Apalutamide adjuvant after RT non-metastatic
        "EMBARK",             # Enzalutamide + leuprolide biochemical recurrence
        "TALAPRO-3",          # Talazoparib + enzalutamide mHSPC
        # Prostate — PARP combinations mCRPC
        "PROpel",             # Olaparib + abiraterone mCRPC
        "MAGNITUDE",          # Niraparib + abiraterone mCRPC
        "BRAVO",              # Niraparib mCRPC
        # Prostate — PSMA theranostics
        "VISION",             # Lu-PSMA-617 mCRPC (landmark)
        "PSMAfore",           # Lu-PSMA mCRPC pre-cabazitaxel
        "PSMAaddition",       # Lu-PSMA mHSPC
        "CLARITY",            # PSMA theranostics high-risk localized
        # Prostate — de-escalation / surveillance
        "PROTECT",            # Active monitoring vs surgery vs RT (long-term update)
        "NeoPro",             # Neoadjuvant enzalutamide + RT
        # Bladder / urothelial
        "JAVELIN Bladder 100",  # Avelumab maintenance 1L urothelial
        "CheckMate 274",      # Nivolumab adjuvant MIBC post-cystectomy
        "EV-302",             # Enfortumab vedotin + pembrolizumab 1L urothelial
        "NILE",               # Durvalumab ± tremelimumab + chemo urothelial
        # Renal
        "KEYNOTE-564",        # Pembrolizumab adjuvant RCC
        "CheckMate 914",      # Nivolumab + ipilimumab adjuvant RCC
    ),
)
