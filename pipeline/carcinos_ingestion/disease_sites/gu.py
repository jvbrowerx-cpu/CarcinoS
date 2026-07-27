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
        # Prostate — landmark mHSPC (establishing combo ADT standard)
        "STAMPEDE",           # Multi-arm platform: docetaxel, abiraterone, RT mHSPC
        "LATITUDE",           # Abiraterone + ADT mHSPC (landmark)
        "CHAARTED",           # Docetaxel + ADT mHSPC (landmark)
        "PEACE-1",            # Abiraterone ± RT mHSPC (docetaxel backbone)
        # Prostate — mHSPC intensification (novel hormonal)
        "ARCHES",             # Enzalutamide + ADT mHSPC
        "ENZAMET",            # Enzalutamide + ADT vs standard-of-care mHSPC
        "TITAN",              # Apalutamide + ADT mHSPC
        "ARASENS",            # Darolutamide + ADT + docetaxel mHSPC
        "ARANOTE",            # Darolutamide + ADT nmCRPC/mHSPC
        "TALAPRO-3",          # Talazoparib + enzalutamide mHSPC
        # Prostate — RT + systemic intensification
        "PEACE-3",            # Radium-223 + enzalutamide mCRPC
        "ENZARAD",            # Enzalutamide + RT high-risk localized prostate
        "ATLAS",              # Apalutamide adjuvant after RT non-metastatic
        "EMBARK",             # Enzalutamide + leuprolide biochemical recurrence
        "RADICALS-HD",        # Short vs long ADT duration with RT prostate
        "RADICALS-RT",        # Adjuvant vs early salvage RT post-prostatectomy
        # Prostate — PARP combinations mCRPC
        "PROpel",             # Olaparib + abiraterone mCRPC
        "MAGNITUDE",          # Niraparib + abiraterone mCRPC
        "TALAPRO-2",          # Talazoparib + enzalutamide mCRPC
        "BRAVO",              # Niraparib mCRPC
        # Prostate — PSMA theranostics
        "VISION",             # Lu-PSMA-617 mCRPC (landmark)
        "PSMAfore",           # Lu-PSMA mCRPC pre-cabazitaxel
        "PSMAaddition",       # Lu-PSMA mHSPC
        "SPLASH",             # Lu-PNT2002 mCRPC
        "CLARITY",            # PSMA theranostics high-risk localized
        "ECLIPSE",            # PSMA PET-guided dose escalation prostate RT
        # Prostate — RT fractionation / technique
        "PACE-A",             # Prostate SBRT vs low-dose-rate brachytherapy
        "PACE-B",             # Prostate SBRT vs conventional/hypofractionated RT
        "PACE-C",             # Prostate SBRT + systemic therapy high-risk
        "HYPO-RT-PC",         # Ultra-hypofractionation vs conventional RT prostate
        "SPPORT",             # Pelvic nodal RT + ADT salvage prostate
        "RAVES",              # Adjuvant vs salvage RT post-prostatectomy (Aus/NZ)
        "GETUG-AFU 17",       # Immediate vs deferred salvage RT prostate
        "NRG-GU009",          # MR-guided hypofractionated RT prostate (NRG)
        "NRG-GU010",          # Prostate SBRT quality of life
        "NRG-GU011",          # Nodal RT prostate cancer
        "RTOG 3505",          # RT ± pelvic nodal irradiation intermediate-risk prostate
        # Prostate — de-escalation / surveillance
        "PROTECT",            # Active monitoring vs surgery vs RT (long-term update)
        "NeoPro",             # Neoadjuvant enzalutamide + RT
        # Bladder / urothelial
        "JAVELIN Bladder 100",  # Avelumab maintenance 1L urothelial
        "CheckMate 274",      # Nivolumab adjuvant MIBC post-cystectomy
        "EV-302",             # Enfortumab vedotin + pembrolizumab 1L urothelial
        "NILE",               # Durvalumab ± tremelimumab + chemo urothelial
        "NIAGARA",            # Durvalumab + chemo perioperative MIBC
        "THOR",               # Erdafitinib vs chemo 2L FGFR+ urothelial
        "AMBASSADOR",         # Pembrolizumab adjuvant MIBC post-cystectomy
        "VOLGA",              # Durvalumab + tremelimumab + EV 1L urothelial
        "SunRISe-1",          # TAR-200 + cetrelimab NMIBC BCG-unresponsive
        "B15",                # BCG + electromotive mitomycin vs BCG alone NMIBC
        # Renal
        "CheckMate 214",      # Nivolumab + ipilimumab vs sunitinib 1L RCC (landmark OS)
        "KEYNOTE-564",        # Pembrolizumab adjuvant RCC
        "KEYNOTE-B61",        # Pembrolizumab + belzutifan 1L RCC
        "CheckMate 914",      # Nivolumab + ipilimumab adjuvant RCC
        "LITESPARK-010",      # Pembrolizumab + belzutifan adjuvant RCC
        "LITESPARK-005",      # Belzutifan vs everolimus advanced RCC
        "LITESPARK-022",      # Belzutifan + lenvatinib vs everolimus + lenvatinib 2L RCC
        "CONTACT-03",         # Cabozantinib + atezolizumab 2L RCC post-IO
        "COSMIC-313",         # Cabozantinib + nivolumab + ipilimumab 1L RCC
        "CheckMate 9ER",      # Nivolumab + cabozantinib 1L RCC
        "CLEAR",              # Lenvatinib + pembrolizumab 1L RCC
        "KEYNOTE-426",        # Pembrolizumab + axitinib 1L RCC
    ),
)
