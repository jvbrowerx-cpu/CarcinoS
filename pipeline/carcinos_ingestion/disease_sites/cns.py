"""CNS — primary brain tumors and brain metastases."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="cns",
    name="Central Nervous System",
    free_text_core=(
        "glioblastoma", "GBM", "glioma",
        "astrocytoma", "oligodendroglioma", "ependymoma",
        "medulloblastoma", "meningioma",
        "primary CNS lymphoma", "PCNSL",
        "brain tumor", "brain tumour",
        "brain metastases", "brain metastasis", "leptomeningeal",
        "diffuse midline glioma", "DMG", "DIPG",
        "spinal cord tumor", "neurocytoma",
    ),
    mesh_headings=(
        "Brain Neoplasms",
        "Central Nervous System Neoplasms",
        "Glioblastoma",
        "Glioma",
        "Astrocytoma",
        "Oligodendroglioma",
        "Ependymoma",
        "Meningioma",
        "Medulloblastoma",
        "Spinal Cord Neoplasms",
        "Brain Stem Neoplasms",
    ),
    modality_terms=(
        # Radiation
        "radiation", "radiotherapy", "IMRT", "proton",
        "stereotactic radiosurgery", "SRS", "gamma knife",
        "stereotactic", "fractionated radiotherapy",
        "whole brain radiotherapy", "WBRT",
        "hippocampal sparing", "memantine",
        "craniospinal", "CSI",
        # Systemic
        "temozolomide", "TMZ", "lomustine", "CCNU", "PCV",
        "bevacizumab", "carmustine wafer",
        # Targeted
        "vorasidenib", "ivosidenib", "IDH",
        "dabrafenib", "trametinib", "BRAF",
        "larotrectinib", "entrectinib", "NTRK",
        # Devices
        "TTFields", "tumor-treating fields", "Optune",
        # Surgery
        "craniotomy", "resection", "gross total resection", "GTR",
        "awake craniotomy", "5-ALA", "fluorescence-guided",
        # Biomarkers
        "MGMT", "IDH1", "IDH2", "1p/19q codeletion",
        "TERT promoter", "ATRX", "EGFRvIII",
        "molecular classification", "WHO grade",
    ),
    site_journals=(
        "Neuro-Oncology",
        "Journal of Neuro-Oncology",
        "Neurology",
        "Acta Neuropathologica",
        "International Journal of Radiation Oncology Biology Physics",
        "Journal of Neurosurgery",
        "Lancet Neurology",
    ),
)
