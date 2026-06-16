"""
Runtime configuration. Reads from environment variables (.env file
recommended for local dev).
"""

from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # NCBI / PubMed
    ncbi_email: str
    ncbi_api_key: str | None

    # OpenAI
    openai_api_key: str | None
    triage_model: str
    deep_review_model: str

    # Supabase
    supabase_url: str | None
    supabase_service_role_key: str | None

    # Pipeline knobs
    max_pmids_per_query: int
    keep_threshold: int
    high_priority_floor: int

    # QS-none (uncertain oncology item) routing thresholds
    #
    # Items that fail Gate 2 (no qualifying signal) go through a three-stage path:
    #
    #   Stage 1 — Relevance gate (deterministic, free):
    #     deterministic_relevance_score < qs_none_min_relevance → HARD REJECT
    #     No LLM call made. Low-relevance junk never reaches mini-triage.
    #
    #   Stage 2 — Pass 1 mini-triage (LLM, triage model):
    #     Pass 1 score >= qs_none_promote_threshold → PROMOTE to Pass 2
    #     Pass 1 score >= qs_none_quarantine_threshold (but < promote) → QUARANTINE_REVIEW
    #     Pass 1 score < qs_none_quarantine_threshold or keep=False → REJECT
    #
    #   Stage 3 — Pass 2 (only promoted items, triage model):
    #     Normal deep review; tiers as A/B/C/NOISE.
    qs_none_min_relevance: int       # deterministic floor before any LLM (default 40)
    qs_none_quarantine_threshold: int  # Pass 1 score floor for quarantine (default 45)
    qs_none_promote_threshold: int     # Pass 1 score floor for Pass 2 promotion (default 65)

    @staticmethod
    def from_env() -> "Config":
        return Config(
            ncbi_email=os.getenv("CARCINOS_NCBI_EMAIL", ""),
            ncbi_api_key=os.getenv("CARCINOS_NCBI_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            triage_model=os.getenv("CARCINOS_TRIAGE_MODEL", "gpt-5.4-mini"),
            deep_review_model=os.getenv("CARCINOS_DEEP_REVIEW_MODEL", "gpt-5.1"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            max_pmids_per_query=int(os.getenv("CARCINOS_MAX_PMIDS", "75")),
            keep_threshold=int(os.getenv("CARCINOS_KEEP_THRESHOLD", "45")),
            high_priority_floor=int(os.getenv("CARCINOS_HIGH_PRIORITY_FLOOR", "25")),
            qs_none_min_relevance=int(os.getenv("CARCINOS_QS_NONE_MIN_RELEVANCE", "40")),
            qs_none_quarantine_threshold=int(os.getenv("CARCINOS_QS_NONE_QUARANTINE_THRESHOLD", "45")),
            qs_none_promote_threshold=int(os.getenv("CARCINOS_QS_NONE_PROMOTE_THRESHOLD", "65")),
        )
