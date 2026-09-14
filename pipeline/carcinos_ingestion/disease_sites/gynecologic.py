"""Gynecologic — reference site that matches the spec doc verbatim."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="gynecologic",
    name="Gynecologic",
    free_text_core=(
        "endometrial", "uterine", "ovarian", "fallopian", "peritoneal",
        "cervical", "cervix", "vulvar", "vulva", "vaginal",
        "gestational trophoblastic",
    ),
    mesh_headings=(
        "Endometrial Neoplasms",
        "Uterine Neoplasms",
        "Ovarian Neoplasms",
        "Fallopian Tube Neoplasms",
        "Uterine Cervical Neoplasms",
        "Vulvar Neoplasms",
        "Vaginal Neoplasms",
        "Gestational Trophoblastic Disease",
    ),
    modality_terms=(
        # Radiation
        "radiation", "radiotherapy", "brachytherapy", "IMRT", "proton",
        "stereotactic", "SBRT",
        # Systemic
        "chemotherapy", "systemic", "platinum", "carboplatin", "cisplatin",
        "paclitaxel", "doxorubicin",
        # IO / targeted
        "immunotherapy", "checkpoint", "PD-1", "PD-L1", "CTLA-4",
        "pembrolizumab", "dostarlimab", "nivolumab",
        "PARP", "olaparib", "niraparib", "rucaparib",
        "bevacizumab", "antiangiogenic", "lenvatinib",
        "trastuzumab", "T-DXd", "mirvetuximab",
        # Surgery
        "surgery", "hysterectomy", "lymphadenectomy", "sentinel",
        "cytoreduction", "debulking",
        # Screening / prevention
        "screening", "HPV", "vaccination",
        # Biomarkers
        "biomarker", "molecular", "genomics",
        "POLE", "p53", "MMR", "MSI", "BRCA", "HRD",
    ),
    site_journals=(
        "Gynecologic Oncology",
        "International Journal of Gynecological Cancer",
        "Radiotherapy and Oncology",
        "International Journal of Radiation Oncology Biology Physics",
    ),
    watched_trials=(
        # Cervical
        "OUTBACK",            # Adjuvant chemo after CRT locally advanced cervical
        "KEYNOTE-A18",        # Pembrolizumab + chemoRT locally advanced cervical
        "ENGOT-cx11",         # Same trial (alternate name)
        "KEYNOTE-826",        # Pembrolizumab 1L persistent/recurrent/metastatic cervical
        "BEATcc",             # Atezolizumab + bevacizumab + chemo cervical
        "INTERLACE",          # Induction chemo + CRT locally advanced cervical
        "CALLA",              # Durvalumab + CRT locally advanced cervical
        "EMPOWER-Cervical 1", # Cemiplimab 2L cervical
        # Endometrial
        "RUBY",               # Dostarlimab adjuvant endometrial (ENGOT-EN6-NSGO)
        "ENGOT-EN6",          # Same trial (alternate name)
        "KEYNOTE-868",        # Pembrolizumab + carboplatin/paclitaxel endometrial
        "NRG-GY020",          # Same trial (NRG arm)
        "NRG-GY018",          # Pembrolizumab + carbo/pac 1L endometrial (NRG designation)
        "DUO-E",              # Durvalumab ± olaparib 1L advanced endometrial
        "AtTEnd",             # Atezolizumab + chemo endometrial
        "GY018",              # Pembrolizumab + carbo/pac 1L endometrial (KEYNOTE-868)
        "LEAP-001",           # Lenvatinib + pembrolizumab vs chemo 1L endometrial
        "DOMENICA",           # Dostarlimab combinations endometrial
        # Ovarian
        "SOLO-1",             # Olaparib maintenance 1L BRCA ovarian
        "SOLO-2",             # Olaparib 2L BRCA+ ovarian (long-term OS)
        "PRIMA",              # Niraparib maintenance 1L ovarian
        "PAOLA-1",            # Olaparib + bevacizumab maintenance ovarian
        "DUO-O",              # Durvalumab + bevacizumab + chemo 1L ovarian
        "FIRST",              # Niraparib + bevacizumab 1L ovarian
        "MIRASOL",            # Mirvetuximab soravtansine FRα+ platinum-resistant ovarian
        "ATHENA-MONO",        # Rucaparib maintenance 1L ovarian
        "NRG-GY004",          # Olaparib ± cediranib vs chemo platinum-resistant ovarian
        # Endometrial RT
        "PORTEC-3",           # Chemo + EBRT vs EBRT high-risk endometrial adjuvant
        "PORTEC-4a",          # MRI/biomarker-guided adjuvant endometrial RT vs brachytherapy
    ),
)
