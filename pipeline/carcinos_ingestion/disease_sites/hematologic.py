"""Hematologic — lymphoma, leukemia, myeloma, MDS, MPN, transplant."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="hematologic",
    name="Hematologic",
    free_text_core=(
        "lymphoma", "Hodgkin lymphoma", "Hodgkin's", "non-Hodgkin",
        "diffuse large B-cell", "DLBCL",
        "follicular lymphoma", "mantle cell lymphoma", "MCL",
        "marginal zone lymphoma", "MZL",
        "T-cell lymphoma", "PTCL", "CTCL",
        "Burkitt lymphoma", "Waldenstrom",
        "leukemia", "AML", "acute myeloid",
        "ALL", "acute lymphoblastic",
        "CLL", "chronic lymphocytic",
        "CML", "chronic myeloid",
        "multiple myeloma", "myeloma", "smoldering myeloma", "MGUS",
        "plasma cell leukemia", "amyloidosis",
        "myelodysplastic syndrome", "MDS",
        "myeloproliferative neoplasm", "MPN",
        "myelofibrosis", "polycythemia vera", "essential thrombocythemia",
        "hairy cell leukemia",
    ),
    mesh_headings=(
        "Lymphoma",
        "Lymphoma, Non-Hodgkin",
        "Hodgkin Disease",
        "Lymphoma, Large B-Cell, Diffuse",
        "Lymphoma, Follicular",
        "Lymphoma, Mantle-Cell",
        "Leukemia",
        "Leukemia, Myeloid, Acute",
        "Precursor Cell Lymphoblastic Leukemia-Lymphoma",
        "Leukemia, Lymphocytic, Chronic, B-Cell",
        "Leukemia, Myelogenous, Chronic, BCR-ABL Positive",
        "Multiple Myeloma",
        "Myelodysplastic Syndromes",
        "Myeloproliferative Disorders",
        "Primary Myelofibrosis",
    ),
    modality_terms=(
        # Lymphoma chemo / antibodies / bispecifics
        "rituximab", "obinutuzumab", "polatuzumab",
        "R-CHOP", "EPOCH", "R-EPOCH",
        "brentuximab", "BV",
        "glofitamab", "epcoritamab", "mosunetuzumab", "odronextamab",
        "loncastuximab",
        "selinexor",
        # CAR-T
        "CAR-T", "CAR T-cell", "chimeric antigen receptor",
        "axicabtagene", "tisagenlecleucel", "lisocabtagene",
        "ide-cel", "cilta-cel", "BCMA",
        # CLL / mantle / Waldenstrom
        "BTK", "ibrutinib", "acalabrutinib", "zanubrutinib", "pirtobrutinib",
        "venetoclax", "BCL2",
        "idelalisib", "duvelisib",
        # Myeloma
        "daratumumab", "isatuximab",
        "teclistamab", "talquetamab", "elranatamab",
        "bortezomib", "carfilzomib", "ixazomib",
        "lenalidomide", "pomalidomide", "thalidomide",
        "elotuzumab", "selinexor",
        # AML / MDS
        "midostaurin", "gilteritinib", "quizartinib",
        "ivosidenib", "enasidenib", "olutasidenib",
        "venetoclax",
        "azacitidine", "decitabine", "luspatercept",
        "magrolimab",
        # CML
        "imatinib", "dasatinib", "nilotinib", "ponatinib", "asciminib",
        # MPN
        "ruxolitinib", "fedratinib", "momelotinib", "pacritinib",
        # Transplant
        "allogeneic", "autologous", "stem cell transplant",
        "HSCT", "allo-HSCT", "auto-HSCT",
        "graft-versus-host", "GVHD",
        # Radiation (limited but real)
        "radiation", "radiotherapy", "involved-site",
        "ISRT", "TBI", "total body irradiation",
        # Biomarkers
        "MRD", "minimal residual disease", "ctDNA",
        "next-generation sequencing", "NGS", "flow cytometry",
        "IGH", "TP53",
    ),
    site_journals=(
        "Blood",
        "Leukemia",
        "Lancet Haematology",
        "British Journal of Haematology",
        "Haematologica",
        "Bone Marrow Transplantation",
        "Hematological Oncology",
        "American Journal of Hematology",
    ),
)
