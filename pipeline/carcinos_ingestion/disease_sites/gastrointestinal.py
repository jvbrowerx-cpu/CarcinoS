"""Gastrointestinal — colorectal, gastric/GEJ, esophageal, pancreatic,
HCC, biliary, anal, neuroendocrine."""

from .base import DiseaseSiteConfig

CONFIG = DiseaseSiteConfig(
    code="gastrointestinal",
    name="Gastrointestinal",
    free_text_core=(
        "colorectal cancer", "CRC",
        "colon cancer", "rectal cancer",
        "gastric cancer", "stomach cancer",
        "gastroesophageal junction", "GEJ",
        "esophageal cancer", "esophageal adenocarcinoma",
        "esophageal squamous cell",
        "pancreatic cancer", "pancreatic adenocarcinoma", "PDAC",
        "hepatocellular carcinoma", "HCC", "liver cancer",
        "cholangiocarcinoma", "biliary tract cancer",
        "intrahepatic cholangiocarcinoma", "extrahepatic cholangiocarcinoma",
        "gallbladder cancer",
        "anal cancer", "anal squamous cell",
        "small bowel cancer", "small intestinal",
        "appendiceal", "pseudomyxoma peritonei",
        "neuroendocrine tumor", "NET", "carcinoid",
        "MSI-H", "dMMR", "mismatch repair deficient",
    ),
    mesh_headings=(
        "Colorectal Neoplasms",
        "Colonic Neoplasms",
        "Rectal Neoplasms",
        "Stomach Neoplasms",
        "Esophageal Neoplasms",
        "Esophagogastric Junction",
        "Pancreatic Neoplasms",
        "Liver Neoplasms",
        "Carcinoma, Hepatocellular",
        "Bile Duct Neoplasms",
        "Cholangiocarcinoma",
        "Gallbladder Neoplasms",
        "Anus Neoplasms",
        "Neuroendocrine Tumors",
        "Carcinoid Tumor",
        "Intestinal Neoplasms",
    ),
    modality_terms=(
        # Cytotoxics
        "FOLFOX", "FOLFIRI", "FOLFIRINOX", "NALIRIFOX",
        "5-FU", "fluorouracil", "capecitabine",
        "oxaliplatin", "irinotecan",
        "gemcitabine", "nab-paclitaxel", "Abraxane",
        "trifluridine", "tipiracil", "TAS-102",
        "mitomycin", "cisplatin",
        # Targeted
        "bevacizumab", "ramucirumab", "ziv-aflibercept",
        "cetuximab", "panitumumab",
        "encorafenib", "BRAF V600E", "binimetinib",
        "regorafenib", "fruquintinib",
        "trastuzumab", "trastuzumab deruxtecan", "T-DXd",
        "tucatinib",
        "zolbetuximab", "claudin",
        "pemigatinib", "futibatinib", "FGFR",
        "ivosidenib", "IDH1",
        "larotrectinib", "entrectinib", "NTRK",
        "selpercatinib", "RET",
        # IO
        "pembrolizumab", "nivolumab", "ipilimumab",
        "durvalumab", "tremelimumab", "atezolizumab",
        "checkpoint", "PD-1", "PD-L1",
        # HCC-specific
        "lenvatinib", "sorafenib", "cabozantinib",
        "TARE", "TACE", "Y-90", "yttrium-90",
        "SBRT liver", "ablation", "radiofrequency ablation",
        # Pancreatic / NET
        "olaparib", "PARP",
        "lutetium-177 dotatate", "Lutathera", "PRRT",
        "everolimus", "sunitinib", "octreotide", "lanreotide",
        # Surgery / local
        "surgical resection", "Whipple", "pancreaticoduodenectomy",
        "low anterior resection", "abdominoperineal resection",
        "total mesorectal excision", "TME",
        "cytoreductive surgery", "HIPEC",
        "watch and wait", "organ preservation",
        # Radiation
        "radiation", "radiotherapy", "IMRT", "proton",
        "chemoradiation", "neoadjuvant chemoradiotherapy",
        "total neoadjuvant therapy", "TNT",
        "SBRT", "stereotactic body",
        # Biomarkers
        "MSI", "MSI-H", "dMMR", "MMR-deficient",
        "KRAS", "NRAS", "BRAF", "HER2",
        "ctDNA", "MRD", "minimal residual disease",
    ),
    site_journals=(
        "Gut",
        "Gastroenterology",
        "Hepatology",
        "Journal of Hepatology",
        "Lancet Gastroenterology and Hepatology",
        "Annals of Surgery",
        "Diseases of the Colon and Rectum",
        "International Journal of Radiation Oncology Biology Physics",
    ),
    watched_trials=(
        # Rectal — total neoadjuvant / de-escalation
        "PROSPECT",           # FOLFOX vs CRT in locally advanced rectal (non-inferiority)
        "RAPIDO",             # Short-course RT + systemic vs CRT rectal
        "STELLAR",            # CRT vs short-course RT + CAPOX rectal
        "OPRA",               # Organ preservation after TNT rectal
        "PRODIGE-23",         # TNT rectal cancer
        # CRC — neoadjuvant / perioperative
        "NICHE-2",            # Neoadjuvant nivolumab + ipilimumab dMMR colon cancer
        "FOxTROT",            # Neoadjuvant FOLFOX vs upfront surgery colon cancer
        "BREAKWATER",         # Encorafenib + cetuximab ± chemo 1L BRAF V600E CRC
        "PARADIGM",           # Panitumumab vs bevacizumab 1L left-sided RAS-wt CRC
        "FIRE-4",             # Cetuximab rechallenge 3L RAS-wt CRC
        # CRC — systemic / targeted
        "KEYNOTE-177",        # Pembrolizumab vs chemo 1L dMMR/MSI-H CRC (OS update)
        "SUNLIGHT",           # Trifluridine/tipiracil + bevacizumab 3L CRC
        "FRESCO-2",           # Fruquintinib 3L CRC
        "CodeBreaK 300",      # Sotorasib + panitumumab KRAS G12C CRC
        "KRYSTAL-1",          # Adagrasib KRAS G12C CRC/NSCLC (basket)
        "MOUNTAINEER",        # Tucatinib + trastuzumab HER2-amplified CRC
        "DESTINY-CRC02",      # T-DXd HER2-overexpressing CRC
        "DYNAMIC-III",        # ctDNA-guided adjuvant chemotherapy stage III colon
        # Esophageal / gastric / GEJ
        "ESOPEC",             # FLOT vs CROSS perioperative esophageal adenocarcinoma
        "Neo-AEGIS",          # Perioperative chemo vs CRT esophageal/GEJ
        "TOPGEAR",            # Chemo + CRT vs chemo perioperative gastric
        "CheckMate 577",      # Nivolumab adjuvant esophageal/GEJ after CRT + surgery
        "KEYNOTE-590",        # Pembrolizumab + chemo 1L esophageal
        "KEYNOTE-811",        # Pembrolizumab + chemo + trastuzumab 1L gastric HER2+
        "KEYNOTE-859",        # Pembrolizumab + chemo 1L gastric/GEJ HER2-negative
        "MATTERHORN",         # Durvalumab + FLOT gastric/GEJ perioperative
        "DANTE",              # Atezolizumab + FLOT gastric perioperative
        "SPOTLIGHT",          # Zolbetuximab + mFOLFOX6 CLDN18.2+ gastric/GEJ
        "GLOW",               # Zolbetuximab + CAPOX CLDN18.2+ gastric/GEJ
        "RATIONALE-302",      # Tislelizumab vs chemo 2L esophageal squamous
        # Biliary / pancreatic
        "TOPAZ-1",            # Durvalumab + gemcitabine/cisplatin 1L biliary tract
        "KEYNOTE-966",        # Pembrolizumab + gemcitabine/cisplatin 1L biliary
        "SWOG 1815",          # Gem/cis vs gem/cis/nab-paclitaxel 1L biliary
        "PRODIGE 24",         # mFOLFIRINOX vs gemcitabine adjuvant pancreatic
        "POLO",               # Olaparib maintenance pancreatic gBRCA
        "NAPOLI-3",           # NALIRIFOX vs gem + nab-paclitaxel 1L pancreatic
        "RTOG 0848",          # Erlotinib ± chemoRT adjuvant pancreatic (RT question)
        # Peritoneal / cytoreductive
        "PRODIGE 7",          # HIPEC + cytoreductive surgery vs CRS alone CRC peritoneal
        "NRG-CC005",          # Anal canal cancer systemic + RT (NRG GI/anal)
        # HCC
        "EMERALD-1",          # Durvalumab + bevacizumab + TACE HCC
        "LEAP-012",           # Lenvatinib + pembrolizumab + TACE HCC
        "HIMALAYA",           # Durvalumab + tremelimumab 1L HCC (OS updates)
        "KEYNOTE-937",        # Pembrolizumab adjuvant HCC post-resection/ablation
    ),
)
