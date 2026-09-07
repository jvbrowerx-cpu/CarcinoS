"""Sarcoma — soft tissue, bone, GIST, rare connective-tissue tumors."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="sarcoma",
    name="Sarcoma",
    free_text_core=(
        "sarcoma", "soft tissue sarcoma", "STS",
        "leiomyosarcoma", "liposarcoma", "synovial sarcoma",
        "rhabdomyosarcoma", "angiosarcoma",
        "Ewing sarcoma", "Ewing's sarcoma",
        "osteosarcoma", "chondrosarcoma", "chordoma",
        "MPNST", "malignant peripheral nerve sheath",
        "GIST", "gastrointestinal stromal tumor",
        "DFSP", "dermatofibrosarcoma",
        "desmoid tumor", "desmoid-type fibromatosis",
        "myxoid liposarcoma", "dedifferentiated liposarcoma",
        "epithelioid sarcoma", "alveolar soft part sarcoma",
    ),
    mesh_headings=(
        "Sarcoma",
        "Sarcoma, Synovial",
        "Sarcoma, Ewing",
        "Liposarcoma",
        "Leiomyosarcoma",
        "Rhabdomyosarcoma",
        "Hemangiosarcoma",
        "Gastrointestinal Stromal Tumors",
        "Bone Neoplasms",
        "Soft Tissue Neoplasms",
        "Osteosarcoma",
        "Chondrosarcoma",
        "Fibromatosis, Aggressive",
    ),
    modality_terms=(
        # Targeted (GIST drives much of this)
        "imatinib", "sunitinib", "regorafenib", "ripretinib", "avapritinib",
        "KIT", "PDGFRA",
        "pazopanib", "tazemetostat",
        "larotrectinib", "entrectinib", "NTRK",
        "nirogacestat", "gamma secretase",
        # Cytotoxic
        "doxorubicin", "ifosfamide", "trabectedin", "eribulin",
        "gemcitabine", "docetaxel",
        "vincristine", "actinomycin",
        "MAP", "methotrexate",
        # IO
        "pembrolizumab", "nivolumab", "checkpoint",
        # Cellular / advanced
        "afami-cel", "TCR therapy", "MAGE-A4",
        # Surgery
        "limb salvage", "amputation", "wide local excision",
        "compartmental resection", "Mohs",
        # Radiation
        "radiation", "radiotherapy", "preoperative radiotherapy",
        "neoadjuvant radiotherapy", "IMRT", "proton",
        "carbon ion", "stereotactic body", "SBRT",
        # Biomarkers
        "fusion", "FUS-DDIT3", "EWSR1", "SS18-SSX",
        "MDM2 amplification",
    ),
    site_journals=(
        "Sarcoma",
        "Journal of Bone Oncology",
        "Bone & Joint Journal",
        "International Journal of Radiation Oncology Biology Physics",
        "Cancer",
        "European Journal of Cancer",
    ),
    watched_trials=(
        # Soft tissue sarcoma — systemic
        "ARYA-3",             # Pazopanib maintenance STS
        "METEOR-1",           # Cabozantinib advanced STS
        "GeDDiS",             # Gemcitabine + docetaxel vs doxorubicin 1L STS
        "EPAZ",               # Epacadostat + pazopanib advanced STS
        "PEMBROSARC",         # Pembrolizumab + metronomic cyclophosphamide STS
        "SARC028",            # Pembrolizumab STS and bone sarcoma
        "ALLIANCE A091701",   # Cabozantinib + nivolumab advanced STS
        "SPEARHEAD-1",        # Afami-cel (TCR-T) synovial sarcoma / MAGE-A4+
        # Soft tissue sarcoma — RT / local
        "NRG-SA002",          # RT dose escalation STS
        "STRASS",             # Preoperative RT retroperitoneal liposarcoma
        "STRASS2",            # Preoperative chemoRT retroperitoneal liposarcoma
        # Desmoid
        "DeFi",               # Nirogacestat (gamma secretase inhibitor) desmoid tumor
        # Bone sarcoma
        "EURAMOS-1",          # Osteosarcoma — long-term follow-up (still publishing)
        "REGOBONE",           # Regorafenib refractory bone sarcoma
        # GIST
        "INTRIGUE",           # Ripretinib vs sunitinib 2L GIST
        "VOYAGER",            # Avapritinib vs regorafenib 3L+ GIST
        "NAVIGATOR",          # Avapritinib PDGFRA D842V GIST
        # Other rare
        "NRG-SA004",          # Phase II STS NRG
    ),
)
