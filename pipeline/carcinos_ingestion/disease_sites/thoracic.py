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
    watched_trials=(
        # Stage III NSCLC — RT + immunotherapy
        "LAURA",              # Osimertinib consolidation after CRT stage III NSCLC
        "PACIFIC",            # Durvalumab after CRT (landmark, updates ongoing)
        "PACIFIC-2",          # Durvalumab concurrent with CRT stage III
        "PACIFIC-4",          # Durvalumab after SBRT early-stage NSCLC
        "PACIFIC-5",          # Durvalumab consolidation stage III (alternative CRT)
        "RATIONALE-315",      # Tislelizumab + CRT stage III NSCLC
        "CheckMate 73L",      # Nivolumab + ipilimumab vs durvalumab stage III
        # SCLC
        "ADRIATIC",           # Durvalumab ± tremelimumab consolidation LS-SCLC
        "DeLLphi-301",        # Tarlatamab ES-SCLC 2nd-line
        "SKYSCRAPER-01",      # Tiragolumab + atezolizumab vs atezolizumab 1L SCLC
        # Perioperative / adjuvant NSCLC
        "CheckMate 816",      # Nivolumab + chemo neoadjuvant resectable NSCLC
        "CheckMate 77T",      # Nivolumab + chemo neoadjuvant vs adjuvant NSCLC
        "KEYNOTE-671",        # Pembrolizumab perioperative NSCLC
        "KEYNOTE-091",        # Pembrolizumab adjuvant resected NSCLC (PEARLS)
        "AEGEAN",             # Durvalumab perioperative NSCLC
        "POSEIDON",           # Durvalumab + tremelimumab + chemo 1L metastatic NSCLC
        "ADAURA",             # Osimertinib adjuvant EGFR+ NSCLC (long-term OS)
        "NeoADAURA",          # Osimertinib neoadjuvant ± chemo EGFR+ NSCLC
        "ALINA",              # Alectinib adjuvant ALK+ NSCLC
        "MERMAID-1",          # Durvalumab ctDNA-guided adjuvant NSCLC
        # RT / chemoRT
        "RTOG 0617",          # Dose-escalated CRT vs standard-dose CRT NSCLC
        "NRG-LU006",          # Proton vs photon chemoRT locally advanced NSCLC
        # EGFR-mutant NSCLC
        "FLAURA2",            # Osimertinib + chemo 1L EGFR-mutant NSCLC
        "MARIPOSA",           # Amivantamab + lazertinib vs osimertinib 1L EGFR
        "MARIPOSA-2",         # Amivantamab + chemo after osimertinib progression
        "PAPILLON",           # Amivantamab + chemo EGFR exon 20 insertion
        "PALOMA-3",           # Patritumab deruxtecan EGFR+ post-osimertinib
        "INSIGHT 2",          # Tepotinib + osimertinib MET+ post-osimertinib
        # KRAS / other driver mutations
        "KRYSTAL-12",         # Adagrasib vs docetaxel KRAS G12C NSCLC
        "CodeBreak 200",      # Sotorasib vs docetaxel KRAS G12C NSCLC
        # RET+ NSCLC
        "LIBRETTO-431",       # Selpercatinib vs chemo ± pembrolizumab RET+ 1L
        # ADC / 2L
        "TROPION-Lung01",     # Dato-DXd vs docetaxel 2L advanced NSCLC
        # Early-stage RT
        "NRG-LU002",          # SBRT vs IMRT early-stage central/paracentral NSCLC
        # Mesothelioma
        "DREAM3R",            # Durvalumab + chemo mesothelioma
    ),
)
