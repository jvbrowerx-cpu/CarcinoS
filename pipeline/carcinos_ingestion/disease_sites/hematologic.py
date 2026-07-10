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
    watched_trials=(
        # Hodgkin lymphoma
        "SWOG 1826",          # Nivolumab + AVD vs brentuximab vedotin + AVD cHL
        "ECHELON-1",          # Brentuximab + AVD vs ABVD cHL (long-term OS)
        "BREACH",             # Brentuximab + BEACOPP advanced cHL
        # DLBCL / aggressive B-cell
        "POLARIX",            # Polatuzumab vedotin + R-CHP vs R-CHOP 1L DLBCL
        "ECHELON-3",          # Brentuximab + bendamustine + rituximab R/R DLBCL
        "ZUMA-7",             # Axi-cel vs standard of care R/R LBCL
        "TRANSFORM",          # Liso-cel vs standard of care R/R LBCL
        # Follicular / indolent lymphoma
        "SYMPATICO",          # Ibrutinib + venetoclax R/R MCL
        "TRIANGLE",           # Ibrutinib + ASCT MCL
        "SHINE",              # Ibrutinib + BR elderly MCL
        # Multiple myeloma
        "PERSEUS",            # Daratumumab + VRd vs VRd transplant-eligible MM
        "IsKia",              # Isatuximab + carfilzomib + Rd vs KRd MM
        "IMROZ",              # Isatuximab + VRd vs VRd transplant-ineligible MM
        "DETERMINATION",      # KRd + ASCT vs KRd alone MM (long-term)
        "CARTITUDE-4",        # Ciltacabtagene autoleucel vs PVd/DPd 2L MM
        "KarMMa-3",           # Idecabtagene vicleucel vs standard regimens R/R MM
        # CLL
        "CLL14",              # Venetoclax + obinutuzumab CLL (long-term OS)
        "CLL17",              # Venetoclax + ibrutinib vs venetoclax + obinutuzumab CLL
        "GAIA",               # Venetoclax + obinutuzumab fit CLL
        "FLAIR",              # Ibrutinib ± venetoclax vs FCR CLL
        "ALPINE",             # Zanubrutinib vs ibrutinib R/R CLL
        "SEQUOIA",            # Zanubrutinib treatment-naive CLL
        "TRANSCEND-CLL004",   # Lisocabtagene maraleucel R/R CLL
        # AML / MDS
        "VIALE-A",            # Venetoclax + azacitidine 1L AML (long-term OS)
        "AGILE",              # Ivosidenib + azacitidine IDH1-mutated AML
        "QuANTUM-First",      # Quizartinib + chemo FLT3-ITD+ AML
        # Myelofibrosis
        "MANIFEST-2",         # Pelabresib + ruxolitinib JAK-naive MF
        "MOMENTUM",           # Momelotinib vs danusertib symptomatic MF
        "TRANSFORM-1",        # Navitoclax + ruxolitinib MF
    ),
)
