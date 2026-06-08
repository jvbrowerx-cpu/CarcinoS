"""Thoracic — NSCLC, SCLC, mesothelioma, thymoma."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="thoracic",
    name="Thoracic",
    free_text_core=(
        "lung cancer", "NSCLC", "non-small cell lung", "non small cell lung",
        "SCLC", "small cell lung",
        "lung adenocarcinoma", "squamous cell lung", "lung squamous",
        "mesothelioma", "pleural mesothelioma",
        "thymoma", "thymic carcinoma",
        "tracheal", "bronchogenic",
    ),
    mesh_headings=(
        "Lung Neoplasms",
        "Carcinoma, Non-Small-Cell Lung",
        "Small Cell Lung Carcinoma",
        "Adenocarcinoma of Lung",
        "Mesothelioma",
        "Mesothelioma, Malignant",
        "Thymoma",
        "Thymus Neoplasms",
    ),
    modality_terms=(
        # Radiation
        "radiation", "radiotherapy", "SBRT", "stereotactic body",
        "IMRT", "proton", "thoracic radiotherapy", "PCI",
        "prophylactic cranial irradiation",
        # Chemotherapy / standard systemic
        "chemotherapy", "platinum", "carboplatin", "cisplatin",
        "pemetrexed", "docetaxel", "etoposide",
        # IO
        "immunotherapy", "checkpoint", "PD-1", "PD-L1", "CTLA-4",
        "pembrolizumab", "nivolumab", "atezolizumab", "durvalumab",
        "ipilimumab", "tremelimumab", "cemiplimab",
        # Targeted by driver
        "EGFR", "osimertinib", "gefitinib", "erlotinib", "afatinib",
        "ALK", "alectinib", "lorlatinib", "brigatinib", "crizotinib",
        "ROS1", "entrectinib",
        "KRAS", "G12C", "sotorasib", "adagrasib",
        "MET", "capmatinib", "tepotinib",
        "RET", "selpercatinib", "pralsetinib",
        "BRAF", "dabrafenib", "trametinib",
        "HER2", "trastuzumab deruxtecan", "T-DXd",
        "NTRK", "larotrectinib",
        "amivantamab", "lazertinib", "datopotamab",
        # Surgery
        "lobectomy", "pneumonectomy", "VATS", "robotic thoracic",
        # Screening / staging
        "low-dose CT", "LDCT", "lung cancer screening",
        # Biomarkers
        "ctDNA", "MRD", "TMB", "tumor mutational burden",
        "PD-L1 expression", "biomarker",
    ),
    site_journals=(
        "Journal of Thoracic Oncology",
        "Lung Cancer",
        "European Respiratory Journal",
        "Thorax",
        "Chest",
        "International Journal of Radiation Oncology Biology Physics",
    ),
)
