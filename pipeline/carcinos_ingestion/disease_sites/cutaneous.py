"""Cutaneous — melanoma, BCC, cSCC, Merkel cell, cutaneous lymphomas."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="cutaneous",
    name="Cutaneous",
    free_text_core=(
        "melanoma", "cutaneous melanoma", "uveal melanoma",
        "mucosal melanoma", "acral melanoma",
        "basal cell carcinoma", "BCC",
        "cutaneous squamous cell carcinoma", "cSCC",
        "Merkel cell carcinoma", "MCC",
        "cutaneous lymphoma", "mycosis fungoides", "Sezary syndrome",
        "dermatofibrosarcoma protuberans", "DFSP",
        "sebaceous carcinoma", "cutaneous adnexal",
        "skin cancer", "non-melanoma skin cancer",
    ),
    mesh_headings=(
        "Melanoma",
        "Skin Neoplasms",
        "Carcinoma, Basal Cell",
        "Carcinoma, Squamous Cell",
        "Carcinoma, Merkel Cell",
        "Lymphoma, T-Cell, Cutaneous",
        "Mycosis Fungoides",
        "Sezary Syndrome",
        "Dermatofibrosarcoma",
    ),
    modality_terms=(
        # Melanoma IO
        "pembrolizumab", "nivolumab", "ipilimumab",
        "relatlimab", "LAG-3", "Opdualag",
        "atezolizumab",
        "T-VEC", "talimogene", "oncolytic",
        "lifileucel", "tumor-infiltrating lymphocyte", "TIL therapy",
        "tebentafusp", "uveal melanoma",
        # Targeted
        "dabrafenib", "trametinib",
        "encorafenib", "binimetinib",
        "vemurafenib", "cobimetinib",
        "BRAF", "MEK",
        "imatinib", "KIT",
        # Non-melanoma skin
        "cemiplimab", "pembrolizumab",
        "avelumab",
        "vismodegib", "sonidegib", "hedgehog",
        "dostarlimab",
        # Surgery / local therapy
        "Mohs", "wide local excision", "sentinel lymph node biopsy",
        "completion lymph node dissection",
        "electrochemotherapy",
        # Radiation
        "radiation", "radiotherapy", "electron beam",
        "brachytherapy", "superficial radiotherapy", "SRT",
        "adjuvant radiotherapy",
        # Biomarkers
        "BRAF V600", "NRAS", "KIT mutation", "TMB",
        "tumor mutational burden", "PD-L1",
        "Merkel cell polyomavirus", "MCPyV",
    ),
    site_journals=(
        "Journal of Investigative Dermatology",
        "JAMA Dermatology",
        "British Journal of Dermatology",
        "Pigment Cell & Melanoma Research",
        "Journal of the American Academy of Dermatology",
        "Dermatologic Surgery",
        "International Journal of Radiation Oncology Biology Physics",
    ),
    watched_trials=(
        # Melanoma — adjuvant
        "KEYNOTE-716",        # Pembrolizumab adjuvant stage IIB/C melanoma
        "CheckMate 76K",      # Nivolumab adjuvant stage IIB/C melanoma
        "KEYNOTE-522",        # (melanoma version if applicable)
        "RELATIVITY-047",     # Relatlimab + nivolumab vs nivolumab 1L advanced melanoma
        "DREAMseq",           # BRAF+MEKi vs IO sequencing strategy melanoma
        "COMBI-AD",           # Dabrafenib + trametinib adjuvant BRAF+ melanoma (long-term)
        "IMspire150",         # Atezolizumab + cobimetinib + vemurafenib BRAF+ melanoma
        # Merkel cell
        "KEYNOTE-017",        # Pembrolizumab MCC (long-term updates)
        "JAVELIN Merkel 200", # Avelumab MCC
        # cSCC / BCC
        "KEYNOTE-630",        # Pembrolizumab adjuvant high-risk cSCC
        "EMPOWER-CSCC-1",     # Cemiplimab locally advanced/metastatic cSCC
        "Checkmate 9ER",      # (not cutaneous — exclude)
    ),
)
