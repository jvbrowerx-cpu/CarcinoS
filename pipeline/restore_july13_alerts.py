"""
restore_july13_alerts.py

Restores the 8-card CarcinoS issue for the week of July 13, 2026.
Sources: original email digest + ChatGPT memory reconstruction + editorial review.

Final card count:
  Practice Impacting (Tier A): 3
  Incremental (Tier B):        5
  Horizon (Tier C):            0  — not confidently recovered; skip

Inserts all as PUBLISHED with published_at = 2026-07-13 so they appear in the
archive for that week but NOT in the current week (July 20).

Run from the pipeline/ directory:
    cd pipeline
    python restore_july13_alerts.py

Requires:
    pip install supabase
    SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY set in carcinos_ingestion/.env
"""

from __future__ import annotations
import hashlib
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
env_file = Path(__file__).parent / "carcinos_ingestion" / ".env"
if env_file.exists():
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

try:
    from supabase import create_client
except ImportError:
    print("ERROR: supabase not installed. Run: pip install supabase")
    sys.exit(1)

url = os.environ.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not url or not key or "YOURPROJECT" in url:
    print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set in .env")
    sys.exit(1)

sb = create_client(url, key)

# ---------------------------------------------------------------------------
# Week anchor — Monday July 13. published_at < July 14 keeps these out of
# the current week (July 20) digest, which queries back 7 days from July 21.
# ---------------------------------------------------------------------------
PUBLISHED_AT = "2026-07-13T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_site_id(code: str) -> str:
    r = sb.table("disease_sites").select("id").eq("code", code).limit(1).execute()
    if not r.data:
        raise RuntimeError(f"disease_site code {code!r} not found in database")
    return r.data[0]["id"]


def upsert_source(title: str, journal: str, pub_date: str, source_type: str) -> str:
    text_hash = hashlib.sha256(f"manual-restore-{title}".encode()).hexdigest()
    try:
        resp = sb.table("sources").insert({
            "type": source_type,
            "title": title[:500],
            "venue": journal,
            "year": 2026,
            "url": "",
            "text_hash": text_hash,
            "raw_text": f"{title} — {journal} — {pub_date} (manually restored)",
        }).execute()
        return resp.data[0]["id"]
    except Exception:
        existing = sb.table("sources").select("id").eq("text_hash", text_hash).limit(1).execute()
        if not existing.data:
            raise
        return existing.data[0]["id"]


def insert_alert(a: dict, site_ids: dict) -> str:
    source_id = upsert_source(
        title=a["title"],
        journal=a["journal"],
        pub_date=a["pub_date"],
        source_type=a["source_type"],
    )

    summary_json = {
        "journal": a["journal"],
        "publication_date": a["pub_date"],
        "evidence_strength": a["evidence_strength"],
        "carcinos_one_liner": a["one_liner"],
        "regimen_description": a.get("study_design", ""),
        "key_results": {"effect_size": a.get("effect_size", "")},
        "population": a.get("population", ""),
        "tier_rationale": "Manually restored — week of July 13 2026",
        "who_should_care": [],
        "sources": [{
            "source_id": source_id,
            "journal": a["journal"],
            "publication_date": a["pub_date"],
            "url": "",
        }],
        "trial": {"name": a.get("trial_name", a["title"]), "nct_ids": [], "doi": None},
        "grounded": True,
        "manually_restored": True,
        "restore_note": "Restored from email digest + ChatGPT memory — week of July 13, 2026",
    }

    resp = sb.table("alerts").insert({
        "disease_site_id": site_ids[a["site"]],
        "primary_source_id": source_id,
        "tier": a["tier"],
        "status": "PUBLISHED",
        "title": a["title"][:500],
        "primary_endpoint": a.get("primary_endpoint", "NOT_REPORTED"),
        "summary_json": summary_json,
        "has_conflict": False,
        "notify": False,
        "radiation_oncology_relevance": a.get("radiation_oncology_relevance", "none"),
        "published_at": PUBLISHED_AT,
    }).execute()

    alert_id = resp.data[0]["id"]
    sb.table("alert_audit_log").insert({
        "alert_id": alert_id,
        "action": "manually_restored",
        "diff": {"note": "Restored from email digest + ChatGPT memory — week of July 13, 2026"},
    }).execute()
    return alert_id


# ---------------------------------------------------------------------------
# Alert definitions — final 8-card issue, week of July 13, 2026
# ---------------------------------------------------------------------------
ALERTS = [

    # ══ PRACTICE IMPACTING — Tier A (3 cards) ═══════════════════════════════

    {   # GU — KEYNOTE-B15/EV-304, perioperative pembro + EV in MIBC
        "title": (
            "FDA approves pembrolizumab or pembrolizumab and berahyaluronidase "
            "alfa-pmph each with enfortumab vedotin-ejfv for muscle invasive "
            "bladder cancer"
        ),
        "tier": "A", "site": "gu",
        "evidence_strength": "A",
        "journal": "FDA / KEYNOTE-B15–EV-304", "pub_date": "July 10, 2026",
        "trial_name": "KEYNOTE-B15 / EV-304",
        "population": (
            "Patients with previously untreated muscle-invasive urothelial bladder cancer "
            "who were candidates for radical cystectomy and eligible for cisplatin-based "
            "chemotherapy."
        ),
        "study_design": (
            "Phase 3 RCT — neoadjuvant pembrolizumab + enfortumab vedotin → cystectomy → "
            "adjuvant pembrolizumab + EV vs neoadjuvant gemcitabine-cisplatin → surgery"
        ),
        "effect_size": (
            "EFS and OS both statistically significant; median EFS not reached in "
            "experimental arm; higher pathologic complete-response rate vs gem-cis"
        ),
        "one_liner": (
            "Perioperative pembrolizumab plus enfortumab vedotin establishes a new "
            "systemic-treatment option for cisplatin-eligible MIBC and challenges "
            "neoadjuvant cisplatin-based chemotherapy as the sole standard perioperative "
            "approach."
        ),
        "source_type": "journal",
        "primary_endpoint": "EFS, OS",
        "radiation_oncology_relevance": "indirect",
    },

    {   # Breast — Gedatolisib FDA approval (VIKTORIA-1)
        "title": "FDA approves gedatolisib plus fulvestrant, with or without palbociclib",
        "tier": "A", "site": "breast",
        "evidence_strength": "A",
        "journal": "FDA / VIKTORIA-1", "pub_date": "July 14, 2026",
        "trial_name": "VIKTORIA-1",
        "population": (
            "Adults with HR-positive, HER2-negative inoperable locally advanced or "
            "metastatic breast cancer without a detected PIK3CA mutation, following "
            "progression on at least one endocrine-therapy regimen in the metastatic setting."
        ),
        "study_design": (
            "Phase 3 RCT — gedatolisib + fulvestrant + palbociclib vs "
            "gedatolisib + fulvestrant vs fulvestrant alone (VIKTORIA-1)"
        ),
        "effect_size": (
            "Median PFS 9.3 mo (gedatolisib + fulvestrant + palbociclib) vs 2.0 mo "
            "(fulvestrant alone), HR 0.24; gedatolisib + fulvestrant PFS 7.4 mo, HR 0.33; "
            "ORR ~32%, ~28%, ~1% respectively; OS immature"
        ),
        "one_liner": (
            "Gedatolisib creates a new pathway-directed option after endocrine resistance "
            "in PIK3CA-wild-type HR-positive/HER2-negative advanced breast cancer. The "
            "magnitude of the PFS benefit is substantial, although toxicity and the burden "
            "of an intravenous regimen will influence sequencing."
        ),
        "source_type": "journal",
        "primary_endpoint": "PFS",
        "radiation_oncology_relevance": "indirect",
    },

    {   # Thoracic — Selpercatinib traditional approval, RET fusion+ solid tumors
        "title": "Selpercatinib receives traditional approval for RET fusion-positive solid tumors",
        "tier": "A", "site": "thoracic",
        "evidence_strength": "A",
        "journal": "FDA / LIBRETTO-001", "pub_date": "July 14, 2026",
        "trial_name": "LIBRETTO-001",
        "population": (
            "Adults with locally advanced or metastatic RET fusion-positive solid tumors "
            "that progressed after prior systemic treatment or had no satisfactory "
            "alternative therapy."
        ),
        "study_design": (
            "Selpercatinib monotherapy in the LIBRETTO-001 tumor-agnostic cohort "
            "(conversion of accelerated to traditional approval)"
        ),
        "effect_size": (
            "ORR 47% across 75 patients; median duration of response 24.5 months; "
            "responses in pancreatic, colorectal, salivary, biliary, breast, ovarian, "
            "neuroendocrine and soft-tissue tumors"
        ),
        "one_liner": (
            "The approval confirms that rare RET fusions are durably actionable across "
            "adult solid tumors and supports broad genomic profiling when patients have "
            "uncommon cancers or limited standard options."
        ),
        "source_type": "journal",
        "primary_endpoint": "ORR",
        "radiation_oncology_relevance": "indirect",
    },

    # ══ INCREMENTAL — Tier B (5 cards) ══════════════════════════════════════

    {   # Thoracic — perioperative chemoimmunotherapy consensus (AIOT)
        "title": (
            "International expert panel endorses perioperative chemoimmunotherapy "
            "for resectable stage II-III NSCLC"
        ),
        "tier": "B", "site": "thoracic",
        "evidence_strength": "B",
        "journal": "Lung Cancer", "pub_date": "July 2026",
        "trial_name": "",
        "population": (
            "Patients with resectable stage II-III non-small-cell lung cancer being "
            "considered for neoadjuvant or perioperative systemic treatment."
        ),
        "study_design": (
            "International expert-panel recommendations (Italian Association of Thoracic "
            "Oncology) based on available randomized evidence"
        ),
        "effect_size": (
            "Panel supports perioperative chemoimmunotherapy as new standard for suitable "
            "patients; endorses invasive mediastinal staging and molecular testing before "
            "treatment selection"
        ),
        "one_liner": (
            "The paper consolidates a rapidly changing treatment landscape into practical "
            "recommendations and reinforces that resectable stage II-III NSCLC should now "
            "be assessed through an integrated thoracic multidisciplinary pathway before "
            "surgery."
        ),
        "source_type": "journal",
        "primary_endpoint": "NOT_REPORTED",
        "radiation_oncology_relevance": "direct",
    },

    {   # Cutaneous — cSCC staging and surveillance imaging consensus (JAMA Derm)
        "title": (
            "Consensus Guidelines for Staging and Surveillance Imaging in Cutaneous "
            "Squamous Cell Carcinoma"
        ),
        "tier": "B", "site": "cutaneous",
        "evidence_strength": "B",
        "journal": "JAMA Dermatology", "pub_date": "July 8, 2026",
        "trial_name": "",
        "population": (
            "Adults with localized cutaneous squamous cell carcinoma being evaluated "
            "for staging or post-treatment surveillance."
        ),
        "study_design": (
            "Multidisciplinary Delphi consensus — 45 experts across dermatology, surgical "
            "oncology, radiation oncology, medical oncology, radiology, pathology, and "
            "otolaryngology"
        ),
        "effect_size": (
            "Imaging recommended for metastatic risk ≥15%; CT preferred for nodal "
            "evaluation; surveillance ≥2 years (near-consensus for 3 years in high-risk); "
            "staging triggers include bone invasion, deep invasion, LPNI, tumors ≥4 cm"
        ),
        "one_liner": (
            "This consensus provides the clearest multidisciplinary framework to date for "
            "when imaging is appropriate in localized high-risk cSCC, reducing practice "
            "variation and supporting more standardized staging and surveillance. While "
            "based on expert consensus rather than prospective trials, it is immediately "
            "applicable to multidisciplinary management of high-risk cSCC."
        ),
        "source_type": "guideline",
        "primary_endpoint": "NOT_REPORTED",
        "radiation_oncology_relevance": "direct",
    },

    {   # CNS/RT — radiation necrosis consensus
        # Note: ChatGPT flagged exact title/DOI as uncertain — verify before citing.
        "title": (
            "European multidisciplinary consensus recommendations on diagnosis and "
            "management of radiation necrosis after brain irradiation"
        ),
        "tier": "B", "site": "cns",
        "evidence_strength": "B",
        "journal": "European multidisciplinary consensus publication", "pub_date": "July 2026",
        "trial_name": "",
        "population": (
            "Adults with suspected or confirmed radiation necrosis after stereotactic or "
            "conventionally fractionated brain irradiation."
        ),
        "study_design": "Expert consensus — diagnosis and management of radiation necrosis",
        "effect_size": (
            "Recommends: MRI + advanced imaging for diagnosis; observation for stable "
            "asymptomatic lesions; corticosteroids for symptomatic edema; bevacizumab for "
            "persistent/significant RN; surgery/LITT for refractory cases or mass effect"
        ),
        "one_liner": (
            "The consensus provides a useful practical framework for a common but variably "
            "managed complication of CNS radiotherapy, standardizing assessment and "
            "treatment rather than introducing a fundamentally new intervention."
        ),
        "source_type": "guideline",
        "primary_endpoint": "NOT_REPORTED",
        "radiation_oncology_relevance": "direct",
    },

    {   # GI — perioperative tislelizumab in resectable gastric cancer
        "title": (
            "Perioperative tislelizumab plus chemotherapy improves major pathological "
            "response in resectable locally advanced gastric adenocarcinoma"
        ),
        "tier": "B", "site": "gastrointestinal",
        "evidence_strength": "B",
        "journal": "Cancer Cell", "pub_date": "July 2026",
        "trial_name": "",
        "population": (
            "Patients with resectable, locally advanced gastric adenocarcinoma receiving "
            "perioperative treatment."
        ),
        "study_design": "Randomized phase 2 — perioperative chemotherapy +/- tislelizumab",
        "effect_size": (
            "Major pathological response rate ~61.8% with chemoimmunotherapy; "
            "EFS and OS data immature"
        ),
        "one_liner": (
            "The results strengthen the biological and clinical rationale for perioperative "
            "immunotherapy in locally advanced gastric cancer, but pathological response "
            "alone is insufficient to establish a new standard before survival data and "
            "phase III confirmation."
        ),
        "source_type": "journal",
        "primary_endpoint": "Major pathological response",
        "radiation_oncology_relevance": "indirect",
    },

    {   # Precision oncology — erdafitinib RAGNAR tumor-specific analysis
        "title": (
            "Erdafitinib in Patients With Advanced Solid Tumors With FGFR Alterations: "
            "Results of Tumor-Specific Analyses and Secondary Cohorts"
        ),
        "tier": "B", "site": "gu",
        "evidence_strength": "B",
        "journal": "JCO Precision Oncology", "pub_date": "July 2026",
        "trial_name": "RAGNAR",
        "population": (
            "Previously treated adults with advanced solid tumors harboring susceptible "
            "FGFR alterations."
        ),
        "study_design": (
            "Phase 2 histology-agnostic basket trial (RAGNAR) — tumor-specific and "
            "secondary-cohort analyses of erdafitinib monotherapy"
        ),
        "effect_size": (
            "ORR by tumor type: pancreatic ~55.6%, H&N SCC ~33.3%, breast ~31.3%, "
            "NSCLC ~26.1%; substantial variation by tumor and genomic context"
        ),
        "one_liner": (
            "The publication supports molecular-tumor-board consideration of erdafitinib "
            "in selected FGFR-altered cancers but argues against treating FGFR alteration "
            "status as uniformly tumor-agnostic."
        ),
        "source_type": "journal",
        "primary_endpoint": "ORR",
        "radiation_oncology_relevance": "none",
    },

    # ══ HORIZON — Tier C (0 cards) ══════════════════════════════════════════
    # Not restored. ChatGPT could not confidently recover Horizon cards without
    # risking fabrication. Re-run the pipeline or restore from a Supabase
    # backup if Horizon content is needed.
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def restore():
    print(f"Connecting to {url[:40]}...")

    site_codes = {"gu", "breast", "thoracic", "cutaneous", "cns", "gastrointestinal"}
    site_ids = {code: get_site_id(code) for code in site_codes}
    print(f"Resolved {len(site_ids)} disease sites.\n")

    tier_label = {"A": "Practice Impacting", "B": "Incremental", "C": "Horizon"}
    counts = {"A": 0, "B": 0, "C": 0}

    for a in ALERTS:
        insert_alert(a, site_ids)
        tier = a["tier"]
        counts[tier] += 1
        print(f"  ✓ [{tier_label[tier]}] {a['title'][:75]}...")

    total = sum(counts.values())
    print(f"\n✓ Done — {total} alerts restored as PUBLISHED (week of July 13, 2026)")
    print(f"  Practice Impacting: {counts['A']}  |  Incremental: {counts['B']}  |  Horizon: {counts['C']}")
    print("  These will appear in the archive for July 13 but NOT in the current week.")
    print()
    print("  ⚠  Radiation necrosis consensus: title/DOI flagged uncertain by ChatGPT.")
    print("  ⚠  NSCLC perioperative consensus: restored as Incremental (was Practice")
    print("      Impacting in original pipeline run). Edit tier in script if preferred.")


if __name__ == "__main__":
    restore()
