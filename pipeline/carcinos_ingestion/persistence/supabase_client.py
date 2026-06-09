"""
Persistence layer — writes ingested artifacts and alerts to the Supabase
schema defined in 01_schema.sql.

Uses the Supabase Postgrest client with the SERVICE_ROLE key (RLS-bypassing,
server-side only). All writes go to:
  - ingestion_runs   (one row per pipeline invocation, observability)
  - sources          (one row per retrieved PubMed record, text_hash bound)
  - trials           (canonical trial records when an NCT id is present)
  - alerts           (the editorial unit — full §5.1 extraction in summary_json)
  - alert_audit_log  (every state change is recorded)

If supabase-py is not installed, this module raises a clear error at
construction time and the rest of the pipeline still works for dry-run
testing (--no-persist on the CLI).
"""

from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Optional

from ..normalize.canonical import CanonicalCandidate
from ..triage.pass1 import Pass1Result
from ..triage.pass2 import Pass2Result


class SupabaseClient:
    def __init__(
        self,
        url: Optional[str] = None,
        service_role_key: Optional[str] = None,
    ):
        try:
            from supabase import create_client    # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "supabase package is not installed. Run `pip install supabase`."
            ) from e

        url = url or os.getenv("SUPABASE_URL")
        key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment."
            )
        self._client = create_client(url, key)
        self._site_id_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_disease_site_id(self, code: str) -> str:
        if code in self._site_id_cache:
            return self._site_id_cache[code]
        resp = self._client.table("disease_sites").select("id").eq("code", code).limit(1).execute()
        if not resp.data:
            raise RuntimeError(f"disease_site code {code!r} not found in database")
        self._site_id_cache[code] = resp.data[0]["id"]
        return self._site_id_cache[code]

    # ------------------------------------------------------------------
    # ingestion_runs
    # ------------------------------------------------------------------

    def start_run(self, source_lane: str, disease_site_code: Optional[str]) -> str:
        site_id = self.get_disease_site_id(disease_site_code) if disease_site_code else None
        resp = self._client.table("ingestion_runs").insert({
            "source_lane": source_lane,
            "disease_site_id": site_id,
            "status": "running",
        }).execute()
        return resp.data[0]["id"]

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        candidates_found: int,
        candidates_passed_filter: int,
        candidates_extracted: int,
        alerts_created: int,
        error_log: str = "",
    ) -> None:
        self._client.table("ingestion_runs").update({
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "candidates_found": candidates_found,
            "candidates_passed_filter": candidates_passed_filter,
            "candidates_extracted": candidates_extracted,
            "alerts_created": alerts_created,
            "error_log": error_log[:8000] if error_log else None,
        }).eq("id", run_id).execute()

    # ------------------------------------------------------------------
    # sources / trials / alerts
    # ------------------------------------------------------------------

    def upsert_source_and_trial(
        self,
        candidate: CanonicalCandidate,
        raw_xml: str,
    ) -> tuple[str, Optional[str]]:
        """Insert (or fetch) the source row and any associated trial row.
        Returns (source_id, trial_id_or_none)."""

        site_id = self.get_disease_site_id(candidate.cancer_site_code)

        # ---- trial (only if NCT present) ----
        trial_id: Optional[str] = None
        if candidate.nct_ids:
            primary_nct = candidate.nct_ids[0]
            existing = (
                self._client.table("trials").select("id").eq("nct_id", primary_nct).limit(1).execute()
            )
            if existing.data:
                trial_id = existing.data[0]["id"]
            else:
                trial_row = self._client.table("trials").insert({
                    "canonical_name": candidate.title[:200] or primary_nct,
                    "phase": _infer_phase(candidate.publication_types),
                    "disease_site_id": site_id,
                    "keywords": candidate.modality_keywords_present[:20],
                    "nct_id": primary_nct,
                }).execute()
                trial_id = trial_row.data[0]["id"]

        # ---- source ----
        source_payload = {
            "trial_id": trial_id,
            "type": _infer_source_type(candidate.publication_types),
            "title": candidate.title[:500],
            "venue": candidate.journal[:200] if candidate.journal else None,
            "year": _extract_year(candidate.publication_date),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{candidate.pmid}/",
            "doi": candidate.doi,
            "text_hash": candidate.text_hash,
            "raw_text": raw_xml[:300_000],   # protect against absurd payloads
        }
        try:
            inserted = self._client.table("sources").insert(source_payload).execute()
            source_id = inserted.data[0]["id"]
        except Exception:
            # On unique-key collision the source already exists for this hash.
            existing = (
                self._client.table("sources")
                .select("id")
                .eq("text_hash", candidate.text_hash)
                .limit(1)
                .execute()
            )
            if not existing.data:
                raise
            source_id = existing.data[0]["id"]

        return source_id, trial_id

    def insert_alert(
        self,
        candidate: CanonicalCandidate,
        pass1: Pass1Result,
        pass2: Pass2Result,
        source_id: str,
        trial_id: str,
        grounded: bool = True,
        unverified_quotes: list | None = None,
    ) -> str:
        site_id = self.get_disease_site_id(candidate.cancer_site_code)

        summary_json = {
            "trial": {
                "name": candidate.title,
                "nct_ids": candidate.nct_ids,
                "doi": candidate.doi,
            },
            # Top-level fields for direct access by the frontend
            "journal": candidate.journal,
            "publication_date": candidate.publication_date,
            "evidence_strength": pass2.evidence_strength,
            "tier_rationale": pass2.tier_rationale_text,
            "study_design": pass2.parsed.get("study_design"),
            "setting": pass2.parsed.get("setting"),
            "cancer_site_subtype": pass2.parsed.get("cancer_site_subtype"),
            "population": pass2.parsed.get("population"),
            "regimen_description": pass2.parsed.get("regimen_description"),
            "intervention": pass2.parsed.get("intervention"),
            "comparator": pass2.parsed.get("comparator"),
            "primary_endpoint": pass2.parsed.get("primary_endpoint"),
            "key_results": pass2.parsed.get("key_results"),
            "limitations_flags": pass2.parsed.get("limitations_flags") or [],
            "who_should_care": pass2.parsed.get("who_should_care") or [],
            "carcinos_one_liner": pass2.parsed.get("carcinos_one_liner"),
            "why_it_matters": pass2.parsed.get("why_it_matters") or [],
            "grounded": grounded,
            "unverified_quotes": unverified_quotes or [],
            # Nested for backward compatibility
            "results": {
                "primary_endpoint": pass2.parsed.get("primary_endpoint"),
                "key_results": pass2.parsed.get("key_results"),
                "evidence_strength": pass2.evidence_strength,
                "tier_rationale": pass2.tier_rationale_text,
            },
            "classification": {
                "category": pass2.parsed.get("category"),
                "study_design": pass2.parsed.get("study_design"),
                "setting": pass2.parsed.get("setting"),
                "cancer_site_subtype": pass2.parsed.get("cancer_site_subtype"),
                "limitations_flags": pass2.parsed.get("limitations_flags") or [],
                "who_should_care": pass2.parsed.get("who_should_care") or [],
            },
            "sources": [{
                "source_id": source_id,
                "pmid": candidate.pmid,
                "doi": candidate.doi,
                "journal": candidate.journal,
                "publication_date": candidate.publication_date,
                "text_hash": candidate.text_hash,
                "evidence_quotes": pass2.parsed.get("evidence_quotes") or [],
            }],
            "deterministic_relevance_score": candidate.deterministic_relevance_score,
            "pass1": pass1.parsed,
        }

        payload = {
            "trial_id": trial_id,
            "disease_site_id": site_id,
            "primary_source_id": source_id,
            "tier": pass2.final_tier_code,
            "status": "EXTRACTED",
            "title": candidate.title[:500],
            "intent": pass2.parsed.get("setting"),
            "primary_endpoint": pass2.parsed.get("primary_endpoint") or "NOT_REPORTED",
            "confidence_tag": "low_confidence" if candidate.deterministic_low_confidence else None,
            "summary_json": summary_json,
            "has_conflict": False,        # set true downstream if multi-source disagreement
            "notify": pass2.notify,
        }

        resp = self._client.table("alerts").insert(payload).execute()
        alert_id = resp.data[0]["id"]
        self.audit(alert_id, action="extracted", diff={"source": "ingestion_pipeline"})
        return alert_id

    # ------------------------------------------------------------------
    # alert_audit_log
    # ------------------------------------------------------------------

    def audit(self, alert_id: str, *, action: str, diff: dict | None = None, actor_id: str | None = None) -> None:
        self._client.table("alert_audit_log").insert({
            "alert_id": alert_id,
            "actor_id": actor_id,
            "action": action,
            "diff": diff or {},
        }).execute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_TYPE_BY_PUBTYPE = {
    "Practice Guideline": "guideline",
    "Guideline": "guideline",
    "Consensus Development Conference": "guideline",
}


def _infer_source_type(pub_types: list[str]) -> str:
    for pt in pub_types:
        if pt in _SOURCE_TYPE_BY_PUBTYPE:
            return _SOURCE_TYPE_BY_PUBTYPE[pt]
    return "journal"


def _infer_phase(pub_types: list[str]) -> Optional[str]:
    for pt in pub_types:
        low = pt.lower()
        if "phase iii" in low or "phase 3" in low:
            return "3"
        if "phase ii" in low or "phase 2" in low:
            return "2"
        if "phase i" in low or "phase 1" in low:
            return "1"
        if "phase iv" in low or "phase 4" in low:
            return "4"
    return None


def _extract_year(pub_date: str) -> Optional[int]:
    if not pub_date:
        return None
    try:
        return int(pub_date[:4])
    except ValueError:
        return None
