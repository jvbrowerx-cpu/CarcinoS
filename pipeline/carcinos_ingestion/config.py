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

    @staticmethod
    def from_env() -> "Config":
        return Config(
            ncbi_email=os.getenv("CARCINOS_NCBI_EMAIL", ""),
            ncbi_api_key=os.getenv("CARCINOS_NCBI_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            triage_model=os.getenv("CARCINOS_TRIAGE_MODEL", "gpt-4o-mini"),
            deep_review_model=os.getenv("CARCINOS_DEEP_REVIEW_MODEL", "gpt-4o-mini"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            max_pmids_per_query=int(os.getenv("CARCINOS_MAX_PMIDS", "75")),
            keep_threshold=int(os.getenv("CARCINOS_KEEP_THRESHOLD", "45")),
            high_priority_floor=int(os.getenv("CARCINOS_HIGH_PRIORITY_FLOOR", "25")),
        )
