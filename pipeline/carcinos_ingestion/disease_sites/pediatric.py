"""Pediatric Oncology — childhood and adolescent malignancies.

Covers tumors where age-specific biology, protocols, and clinical trials
are distinct from their adult counterparts. Includes overlap entities
(ALL, AML, CNS tumors, sarcomas) but retrieves pediatric-specific trials,
COG/SIOP protocols, and results from dedicated pediatric journals that
would be missed by the adult-focused site queries.
"""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="pediatric",
    name="Pediatric Oncology",
    # Override tumor_terms to include blastoma-suffix tumors (neuroblastoma,
    # hepatoblastoma, medulloblastoma, retinoblastoma, pleuropulmonary blastoma)
    # and pediatric/adolescent qualifiers used in abstract language.
    tumor_terms=(
        "cancer", "carcinoma", "malignancy", "neoplasm", "tumor", "tumour",
        "blastoma", "sarcoma", "leukemia", "leukaemia", "lymphoma",
        "pediatric", "paediatric", "childhood", "adolescent",
    ),
    free_text_core=(
        # Leukemia — most common childhood cancer
        "acute lymphoblastic leukemia", "ALL", "acute lymphoblastic leukaemia",
        "childhood leukemia", "pediatric leukemia", "paediatric leukemia",
        "acute myeloid leukemia", "pediatric AML", "childhood AML",
        # CNS tumors
        "medulloblastoma",
        "DIPG", "diffuse intrinsic pontine glioma",
        "diffuse midline glioma", "H3K27M",
        "pediatric glioma", "paediatric glioma",
        "low-grade glioma", "pediatric low-grade glioma",
        "atypical teratoid rhabdoid tumor", "ATRT",
        "ependymoma", "pediatric ependymoma",
        "craniopharyngioma",
        # Embryonal / solid tumors
        "neuroblastoma",
        "Wilms tumor", "Wilms tumour", "nephroblastoma",
        "hepatoblastoma",
        "retinoblastoma",
        "pleuropulmonary blastoma",
        # Sarcomas — pediatric context
        "rhabdomyosarcoma", "RMS",
        "Ewing sarcoma", "Ewing's sarcoma",
        "osteosarcoma", "pediatric osteosarcoma",
        # Lymphoma — pediatric context
        "pediatric lymphoma", "paediatric lymphoma",
        "anaplastic large cell lymphoma", "ALCL",
        "pediatric Hodgkin", "childhood Hodgkin",
        "Burkitt lymphoma",
        # Histiocytic / rare
        "Langerhans cell histiocytosis", "LCH",
        "juvenile myelomonocytic leukemia", "JMML",
        "pediatric oncology", "paediatric oncology",
        "childhood cancer", "childhood malignancy",
        "adolescent and young adult", "AYA",
    ),
    mesh_headings=(
        "Precursor Cell Lymphoblastic Leukemia-Lymphoma",
        "Leukemia, Myeloid, Acute",
        "Neuroblastoma",
        "Wilms Tumor",
        "Medulloblastoma",
        "Rhabdomyosarcoma",
        "Sarcoma, Ewing",
        "Osteosarcoma",
        "Retinoblastoma",
        "Hepatoblastoma",
        "Lymphoma, Large-Cell, Anaplastic",
        "Brain Stem Neoplasms",
        "Glioma",
        "Ependymoma",
        "Histiocytosis, Langerhans-Cell",
        "Neoplasms",          # paired with Child MeSH via free_text_core age terms
    ),
    modality_terms=(
        # ALL / AML chemotherapy backbones
        "vincristine", "dexamethasone", "asparaginase", "pegaspargase",
        "methotrexate", "high-dose methotrexate",
        "cytarabine", "daunorubicin", "anthracycline",
        "6-mercaptopurine", "thioguanine",
        "blinatumomab",           # BiTE for peds ALL
        "inotuzumab ozogamicin",
        "tisagenlecleucel",       # CAR-T in peds ALL
        "nelarabine",             # T-cell ALL
        "clofarabine",
        # Targeted — ALL/AML
        "dasatinib", "imatinib",  # Ph+ ALL
        "ruxolitinib",            # Ph-like ALL
        "gilteritinib", "quizartinib",   # FLT3 AML
        "venetoclax",
        "gemtuzumab ozogamicin",
        # Neuroblastoma
        "dinutuximab", "dinutuximab beta",
        "isotretinoin", "13-cis-retinoic acid",
        "MIBG", "iobenguane",
        "ALK inhibitor", "crizotinib", "lorlatinib",
        "naxitamab",
        # Wilms / nephroblastoma
        "actinomycin", "dactinomycin",
        "doxorubicin",
        "nephrectomy",
        # Medulloblastoma / CNS
        "craniospinal irradiation", "CSI",
        "proton therapy", "proton beam",
        "ONC201",                 # H3K27M DMG/DIPG
        "dabrafenib", "trametinib",   # BRAF-mutant peds glioma
        "selumetinib",            # NF1-associated glioma
        "binimetinib",
        "tovorafenib",            # peds low-grade glioma
        "BRAF", "MEK",
        "temozolomide",
        "carboplatin", "vincristine",    # peds LGG backbone
        # Rhabdomyosarcoma
        "VAC", "vincristine actinomycin cyclophosphamide",
        "irinotecan", "temsirolimus",
        # Ewing sarcoma / osteosarcoma
        "VDC/IE", "doxorubicin cisplatin",
        "MAP regimen",
        "mifamurtide",
        # Lymphoma
        "CHOP", "ALCL99",
        "brentuximab vedotin",    # peds Hodgkin / ALCL
        # Radiation — peds specific
        "radiation", "radiotherapy",
        "stereotactic radiosurgery", "SRS",
        "photon", "proton",
        # HSCT
        "stem cell transplant", "HSCT", "allogeneic", "autologous",
        # Immunotherapy
        "pembrolizumab", "nivolumab", "atezolizumab",
        "CAR-T", "CAR T-cell",
        # Trial consortia / protocol keywords
        "COG", "Children's Oncology Group",
        "SIOP", "AALL", "ARST", "ACNS", "AREN",
        "BFM", "ITCC",
        "EpSSG",
        # Genomic / biomarker
        "NTRK", "larotrectinib", "entrectinib",
        "RET", "ALK", "ROS1",
        "MYCN amplification",
        "1p/19q", "IDH",
        "next-generation sequencing", "NGS",
        "liquid biopsy", "ctDNA",
        "minimal residual disease", "MRD",
    ),
    site_journals=(
        "Pediatric Blood and Cancer",
        "Pediatric Blood & Cancer",
        "Journal of Pediatric Hematology Oncology",
        "Journal of Pediatric Hematology/Oncology",
        "JCO Pediatric Oncology",
        "Pediatric Oncology",
        "Neuro-Oncology",                              # major peds CNS outlet
        "Lancet Child and Adolescent Health",
        "Lancet Child & Adolescent Health",
        "European Journal of Cancer",
        "Cancer",
        "Clinical Cancer Research",
        "Blood",
        "Annals of Oncology",
    ),
    watched_trials=(
        # ALL
        "AALL0434",       # COG — augmented BFM + nelarabine T-cell ALL
        "AALL1231",       # COG — blinatumomab maintenance B-ALL
        "AALL1732",       # COG — blinatumomab in newly diagnosed B-ALL
        "AALL1931",       # COG — inotuzumab + chemo B-ALL
        "AALL0232",       # COG — dexamethasone vs prednisone standard-risk ALL
        "UKALL 2011",     # UK — pediatric ALL backbone
        "DFCI ALL",       # Dana-Farber consortium ALL
        "BFM 2017",       # Berlin-Frankfurt-Münster ALL
        # AML
        "AAML1031",       # COG — bortezomib in peds AML
        "AAML1831",       # COG — gemtuzumab + CPX-351 peds AML
        # Neuroblastoma
        "ANBL1232",       # COG — dinutuximab + immunotherapy high-risk NB
        "ANBL1221",       # COG — tandem ASCT high-risk NB
        "ANBL2021",       # COG — naxitamab consolidation
        "BEACON",         # MIBG + dinutuximab R/R neuroblastoma
        # Medulloblastoma
        "ACNS0331",       # COG — craniospinal irradiation dose reduction avg-risk MB
        "ACNS1422",       # COG — pemetrexed-based chemo MB
        "SJMB12",         # St. Jude — risk-adapted MB
        # DIPG / diffuse midline glioma
        "ONC201 DIPG",    # ONC201 H3K27M-altered DMG (peds)
        "DIPG-IV",        # ONC201 DIPG H3K27-altered
        "NRG-BN005",      # Radiation + ONC201 DIPG
        "ACNS0126",       # COG — RT + TMZ DIPG
        # Pediatric low-grade glioma
        "ACNS0833",       # COG — carboplatin + vincristine pLGG
        "LOGGIC/FIREFLY", # Tovorafenib BRAF-altered pLGG
        "ILLUMINATE",     # Selumetinib NF1-associated glioma
        # Wilms tumor
        "AREN0532",       # COG — intermediate/high-risk Wilms
        "AREN0533",       # COG — very high-risk Wilms
        "UMBRELLA SIOP",  # SIOP — European Wilms protocol
        # Rhabdomyosarcoma
        "ARST0431",       # COG — intermediate-risk RMS
        "ARST1431",       # COG — low-risk RMS
        "RMS2005",        # European — soft tissue sarcoma children
        "EpSSG RMS 2005", # EpSSG rhabdomyosarcoma
        # Ewing sarcoma
        "AEWS1031",       # COG — VDC/IE + vincristine topotecan cyclophosphamide
        "EE2012",         # Euro Ewing — standard vs high-risk Ewing
        # Osteosarcoma
        "AOST0331",       # COG — MAP vs MAPIE osteosarcoma
        "EURAMOS-1",      # European/American — mifamurtide in osteosarcoma
        # Hodgkin lymphoma — pediatric
        "AHOD1331",       # COG — pembrolizumab in R/R pediatric HL
        "AHOD1231",       # COG — brentuximab + AVD peds advanced HL
        "EuroNet-PHL-C2", # European — pediatric Hodgkin lymphoma
        # ALCL
        "ALCL99",         # European — anaplastic large cell lymphoma
        "ANHL12P1",       # COG — crizotinib in ALK+ ALCL
    ),
)
