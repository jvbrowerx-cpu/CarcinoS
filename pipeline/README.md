# CarcinoS Ingestion Pipeline

Deterministic-first oncology literature ingestion across all 10 CarcinoS disease sites.

This package implements the architecture described in *CarcinoS script and algorithm.docx*:

```
   PubMed E-utilities (deterministic)            ← Step 1: high-recall query, per-site
            │
            ▼
   Hard + fuzzy dedupe                           ← Step 2.1
            │
            ▼
   Pubtype filter (with journal-whitelist override)   ← Step 2.3 / 2.4
            │
            ▼
   Deterministic relevance score (0–100)         ← Step 2.5
            │
            ▼
   Canonical candidate object                    ← Step 2.6 (LLM never sees raw input)
            │
            ▼
   Pass 1 LLM triage (gpt-4o-mini, strict JSON)  ← Step 3 Pass 1
            │
            ▼ (only if KEEP rules pass)
   Pass 2 LLM deep review (gpt-4o, strict JSON)  ← Step 3 Pass 2
            │  + quote-grounding check
            │  + code-enforced tier mapping
            ▼
   Supabase: alerts (status = EXTRACTED)         ← awaits founder editor approval
```

The LLM never decides what to search for, never decides whether something
exists, and never sets the final alert tier. Those are deterministic.
The LLM only synthesizes structured fields, with strict JSON schemas, from
text the deterministic pipeline already vetted.

---

## Disease sites (all 10 implemented)

Codes match the `disease_site_code` enum in `01_schema.sql`:

| Code | Site |
|------|------|
| `gynecologic` | Gynecologic |
| `thoracic` | Thoracic (NSCLC, SCLC, mesothelioma, thymoma) |
| `breast` | Breast |
| `head_neck` | Head and Neck |
| `cns` | Central Nervous System |
| `sarcoma` | Sarcoma (soft tissue, bone, GIST) |
| `gu` | Genitourinary |
| `hematologic` | Hematologic |
| `cutaneous` | Cutaneous (melanoma, BCC, cSCC, MCC) |
| `gastrointestinal` | Gastrointestinal |

Each site has its own module under `disease_sites/` with:
- `free_text_core` — anatomic / disease terms
- `mesh_headings` — PubMed `[MeSH]` neoplasm headings
- `modality_terms` — radiation / systemic / surgery / biomarker keywords
- `site_journals` — site-specific journal whitelist (appended to shared)

---

## Setup

```bash
# 1. Create venv
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Then edit .env to fill in:
#   CARCINOS_NCBI_EMAIL          (required)
#   CARCINOS_NCBI_API_KEY        (optional, raises rate limit 3→10 req/sec)
#   OPENAI_API_KEY               (required for Pass 1/2)
#   SUPABASE_URL                 (required for --persist)
#   SUPABASE_SERVICE_ROLE_KEY    (required for --persist; server-side only)

# 4. Load env (uses python-dotenv if you want)
export $(grep -v '^#' .env | xargs)
```

---

## Usage

### Inspect the queries (no API calls)

```bash
python -m carcinos_ingestion.run --site head_neck --print-query
```

### Dry run for one site (PubMed + filters + LLM, no DB write)

```bash
python -m carcinos_ingestion.run --site gynecologic --days 7 --dry-run
```

### Persist to Supabase

```bash
python -m carcinos_ingestion.run --site head_neck --days 7 --persist
```

Alerts land in the `alerts` table with `status = EXTRACTED`. The founder
editor reviews them in the admin portal and transitions them through
`EDITOR_REVIEW → APPROVED → PUBLISHED` (per `01_schema.sql`).

### Run all 10 sites

```bash
python -m carcinos_ingestion.run --all --persist
```

Designed for cron / a Supabase Scheduled Function. A weekly run at e.g.
Monday 03:00 UTC will populate the editor queue with the previous 7 days
of literature.

---

## How this satisfies the deterministic-first requirement

1. **Search is API-driven, not LLM-driven.** PubMed E-utilities returns
   stable PMIDs; ClinicalTrials.gov NCT IDs are captured directly from
   PubMed metadata.
2. **Every record is hash-bound.** `PubMedRecord.text_hash` is sha256 of
   the exact XML used for downstream extraction — written to
   `sources.text_hash` per the schema's audit guarantee.
3. **The LLM only sees a normalized canonical object.** No raw HTML, no
   external links — only fields that the deterministic stage already
   classified.
4. **Strict JSON schemas at the API layer.** Both passes use OpenAI
   `response_format = { type: "json_schema", strict: true }`. Malformed
   JSON or extra keys are impossible.
5. **Quote-grounding check.** Pass 2 must produce 1–3 short literal
   quotes from the abstract; the pipeline verifies each quote actually
   appears in the source text. Ungrounded results are demoted to Tier C
   and `notify = false`.
6. **Tier mapping is enforced by code.** The LLM's tier choice is a hint;
   `enforce_tier_mapping(impact, evidence, llm_tier)` is authoritative.
7. **Alerts land at `EXTRACTED`, not `PUBLISHED`.** A founder editor must
   approve every alert before it reaches a clinician — the schema has a
   `published_requires_approval` constraint that enforces this even if
   code tries to bypass it.
8. **Full audit trail.** Every alert state change writes to
   `alert_audit_log` with action + actor + JSON diff.

---

## Repository layout

```
carcinos_ingestion/
├── README.md                         ← you are here
├── requirements.txt
├── .env.example
├── config.py                         ← env-var loader
├── run.py                            ← CLI entry point
├── pipeline.py                       ← orchestrator (Step 1-9)
│
├── disease_sites/
│   ├── base.py                       ← shared blocks + DiseaseSiteConfig
│   ├── gynecologic.py                ← reference site (matches spec doc verbatim)
│   ├── thoracic.py
│   ├── breast.py
│   ├── head_neck.py
│   ├── cns.py
│   ├── sarcoma.py
│   ├── gu.py
│   ├── hematologic.py
│   ├── cutaneous.py
│   └── gastrointestinal.py
│
├── retrieval/
│   └── pubmed.py                     ← E-utilities client + XML parser
│
├── filters/
│   ├── dedupe.py                     ← hard (DOI/PMID) + fuzzy (title sim ≥0.92)
│   ├── pubtype.py                    ← drop editorials/letters/case reports
│   └── relevance.py                  ← deterministic 0-100 score
│
├── normalize/
│   └── canonical.py                  ← CanonicalCandidate (LLM input shape)
│
├── triage/
│   ├── schemas.py                    ← strict JSON schemas for Pass 1 / Pass 2
│   ├── openai_client.py              ← thin OpenAI wrapper
│   ├── pass1.py                      ← fast triage + post-LLM keep rules
│   └── pass2.py                      ← deep review + tier mapping + quote check
│
└── persistence/
    └── supabase_client.py            ← write to alerts / sources / trials / audit
```

---

## Next steps (not in this initial pipeline)

- ClinicalTrials.gov second lane (`retrieval/ctgov.py`) — your schema
  already has `'registry'` as a `source_type`, the ingestion lane label
  exists in `ingestion_runs.source_lane`, but the client itself is not
  built yet. Same dedupe-by-NCT logic.
- Conference abstract lanes (ASCO/ESMO/ASTRO).
- Cross-source conflict detection — when two sources for the same trial
  disagree on a numeric claim, set `alerts.has_conflict = true` so the
  spec §5.2 "conflicts block notify" constraint trips.
- Landmark-trial seed scripts per site (`04_landmark_seed_*.sql`) to
  populate `landmark_trials` for the retrospective validation gate.
- Eval harness — run a held-out set of known-good and known-noise PMIDs
  weekly and track precision/recall vs human editor decisions.
