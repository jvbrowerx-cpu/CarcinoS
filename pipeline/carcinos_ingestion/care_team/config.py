"""Settings for the care-team step. All overridable by environment variable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class CareTeamSettings:
    # Master switch. On by default; set CARE_TEAM_ENABLED=false to turn off.
    enabled: bool = field(default_factory=lambda: os.getenv("CARE_TEAM_ENABLED", "true").lower() != "false")
    # Model that writes the rows.
    model: str = field(default_factory=lambda: os.getenv("CARE_TEAM_MODEL", "gpt-6-astra"))
    # Used automatically if the main model call fails (e.g. API not yet supported).
    fallback_model: str = field(default_factory=lambda: os.getenv("CARE_TEAM_FALLBACK_MODEL", "gpt-5.6-terra"))
    # Model that lists drug names for the FDA label lookup (no longer GPT-4o-mini,
    # which retires in January). Defaults to the main model.
    drug_name_model: str = field(default_factory=lambda: os.getenv("CARE_TEAM_DRUG_MODEL", os.getenv("CARE_TEAM_MODEL", "gpt-6-astra")))
    # Which tiers are eligible. Start with Practice Impacting only.
    tiers: list[str] = field(default_factory=lambda: _csv("CARE_TEAM_TIERS", "A"))
    # Statuses the WRITE mode may touch: awaiting review, or approved but not yet sent
    # (hand-added cards are often saved as APPROVED). Published cards are never modified.
    writable_statuses: list[str] = field(default_factory=lambda: _csv("CARE_TEAM_STATUSES", "EXTRACTED,EDITOR_REVIEW,APPROVED"))
    # Pull the ClinicalTrials.gov record (arms, adverse-event tables) for NCT numbers on the card.
    use_registry: bool = field(default_factory=lambda: os.getenv("CARE_TEAM_REGISTRY", "true").lower() == "true")
    # Let the model search the web for primary-source passages. Code downloads each
    # page itself and keeps only quotes found word for word on it.
    use_web_finder: bool = field(default_factory=lambda: os.getenv("CARE_TEAM_WEB_FINDER", "true").lower() == "true")
    # Model used for the web search (must support OpenAI's web search tool).
    finder_model: str = field(default_factory=lambda: os.getenv("CARE_TEAM_FINDER_MODEL", os.getenv("CARE_TEAM_MODEL", "gpt-6-astra")))
    # Look up official FDA labels (openFDA) for approved drugs.
    use_fda_labels: bool = field(default_factory=lambda: os.getenv("CARE_TEAM_FDA_LABELS", "true").lower() == "true")
    # "generate" (default): the model writes every row from what it finds, citing
    # sources; numbers it can't match to downloaded text are flagged for the editor.
    # "verbatim": the stricter original mode (every row backed by exact quotes).
    mode: str = field(default_factory=lambda: os.getenv("CARE_TEAM_MODE", "generate").lower())
