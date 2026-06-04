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
)
