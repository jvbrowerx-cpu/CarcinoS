"""Head and Neck — HNSCC, oral cavity, oropharynx, larynx, hypopharynx,
nasopharynx, salivary gland, sinonasal, thyroid (commonly grouped here).
"""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="head_neck",
    name="Head and Neck",
    free_text_core=(
        "head and neck cancer", "head and neck squamous", "HNSCC",
        "oral cavity", "oropharynx", "oropharyngeal",
        "larynx", "laryngeal",
        "hypopharynx", "hypopharyngeal",
        "nasopharynx", "nasopharyngeal", "NPC",
        "salivary gland", "parotid", "submandibular",
        "sinonasal", "paranasal sinus", "nasal cavity",
        "tongue", "tonsil", "base of tongue",
        "p16-positive", "HPV-positive oropharynx", "HPV-negative",
        "thyroid cancer",
    ),
    mesh_headings=(
        "Head and Neck Neoplasms",
        "Squamous Cell Carcinoma of Head and Neck",
        "Mouth Neoplasms",
        "Oropharyngeal Neoplasms",
        "Laryngeal Neoplasms",
        "Hypopharyngeal Neoplasms",
        "Nasopharyngeal Neoplasms",
        "Nasopharyngeal Carcinoma",
        "Salivary Gland Neoplasms",
        "Paranasal Sinus Neoplasms",
        "Tongue Neoplasms",
        "Tonsillar Neoplasms",
        "Thyroid Neoplasms",
    ),
    modality_terms=(
        # Radiation (heavy in H&N)
        "radiation", "radiotherapy", "IMRT", "VMAT", "proton",
        "stereotactic", "SBRT", "brachytherapy",
        "chemoradiation", "chemoradiotherapy", "concurrent",
        "altered fractionation", "hyperfractionation",
        "adjuvant radiotherapy", "definitive radiotherapy",
        "reirradiation", "re-irradiation",
        # Systemic
        "cisplatin", "carboplatin", "5-FU", "fluorouracil",
        "docetaxel", "TPF", "weekly cisplatin",
        "cetuximab", "EGFR",
        # IO
        "pembrolizumab", "nivolumab", "checkpoint", "PD-1", "PD-L1",
        "PD-L1 CPS", "combined positive score",
        "neoadjuvant immunotherapy",
        # Surgery
        "transoral robotic surgery", "TORS",
        "neck dissection", "selective neck dissection",
        "larynx preservation", "organ preservation",
        "parotidectomy", "thyroidectomy",
        # Biomarkers / surveillance
        "HPV", "p16", "Epstein-Barr virus", "EBV",
        "ctDNA", "HPV ctDNA", "circulating tumor HPV",
        "TIL", "tumor microenvironment",
        # De-escalation
        "de-escalation", "deintensification", "dose reduction",
    ),
    site_journals=(
        "Head & Neck",
        "Oral Oncology",
        "International Journal of Radiation Oncology Biology Physics",
        "Radiotherapy and Oncology",
        "Otolaryngology - Head and Neck Surgery",
        "Laryngoscope",
        "Thyroid",
    ),
    watched_trials=(
        # De-escalation trials — HPV+ oropharyngeal
        "NRG-HN002",          # Phase II de-intensification RT HPV+ OPC
        "NRG-HN005",          # Phase II nivolumab de-escalation HPV+ OPC
        "PATHOS",             # Phase II/III de-escalation post-TORS UK
        "EA3161",             # Phase III omit cisplatin HPV+ OPC (ECOG)
        "ECOG-ACRIN 3311",    # De-escalation transoral surgery HPV+ OPC
        "DART",               # De-escalation after response to induction
        "OPTIMA",             # Response-adaptive de-escalation HPV+ OPC
        # IO + CRT trials
        "KEYNOTE-412",        # Pembrolizumab + CRT vs CRT LA-SCCHN
        "CONTINUUM",          # Nivolumab + CRT oropharyngeal
        "JAVELIN Head and Neck 100",  # Avelumab + CRT (negative, landmark)
        "CheckMate 651",      # Nivolumab + ipilimumab 1L R/M SCCHN
        "KEYNOTE-048",        # Pembrolizumab 1L R/M SCCHN (long-term OS updates)
        # Nasopharyngeal
        "CONTINUUM-NPC",      # NPC immunotherapy
        "CAPTAIN-1st",        # Camrelizumab + chemo 1L NPC
        "JUPITER-02",         # Toripalimab + chemo 1L NPC
        "RATIONALE-309",      # Tislelizumab + chemo NPC
        "DIPPER",             # Capecitabine adjuvant NPC post-CRT
        "GERCOR NPC",         # Capecitabine maintenance NPC
        # Thyroid
        "LIBRETTO-531",       # Selpercatinib vs lenvatinib/sorafenib RET+ thyroid
        "SELECT",             # Lenvatinib RAI-refractory thyroid (updates)
    ),
)
