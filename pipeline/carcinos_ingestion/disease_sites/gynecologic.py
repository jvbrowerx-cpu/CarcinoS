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
)
