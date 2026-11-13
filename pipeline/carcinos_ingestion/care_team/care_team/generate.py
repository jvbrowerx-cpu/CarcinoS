"""Generate and validate the care-team rows for one card."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from .config import CareTeamSettings
from .eligibility import check_eligibility
from .finder import default_searcher, find_verified_excerpts
from .labels import DrugLabel, base_ingredient, fetch_labels
from .prompt import (
    DISCLAIMER,
    NO_EXTERNAL_BLOCK,
    excerpts_block,
    registry_block,
    DRUG_NAMES_SCHEMA,
    DRUG_NAMES_SYSTEM,
    NO_LABELS_BLOCK,
    ROWS_SCHEMA,
    ROWS_SYSTEM,
    ROWS_USER_TEMPLATE,
)
from .sources import fetch_registry, nct_ids_for
from .text import clean_source_text, normalize
from .validate import validate

log = logging.getLogger("carcinos.care_team")

PAPER_CHAR_LIMIT = 20000
# Total FDA-label text shown to the model per card (shared across labels): keeps
# cost and response time reasonable for multi-drug regimens.
LABEL_PROMPT_BUDGET = 120_000


def _structured(client, settings: CareTeamSettings, model: str, **kw):
    """Call the model; fall back once to the fallback model if the call fails."""
    try:
        return client.structured(model=model, **kw), model
    except Exception as err:
        fb = settings.fallback_model
        if not fb or fb == model:
            raise
        log.warning("care-team: %s failed (%s); retrying with %s", model, err, fb)
        return client.structured(model=fb, **kw), fb


def _card_context(alert: dict) -> str:
    s = alert.get("summary_json") or {}
    kr = s.get("key_results") or {}
    return " ".join(str(x) for x in [
        alert.get("title") or "", s.get("intervention") or "", s.get("regimen_description") or "",
        s.get("population") or "", s.get("carcinos_one_liner") or "",
        kr.get("effect_size") if isinstance(kr, dict) else kr, s.get("disease_site_code") or "",
    ] if x)


def _drug_named_in_card(drug: str, alert: dict, paper_text: str) -> bool:
    """Deterministic check: only use a label for a drug the card itself names
    (matched on the core ingredient, so name variants don't matter)."""
    base = base_ingredient(drug)
    hay = normalize(_card_context(alert) + " " + (paper_text or ""))
    return bool(base) and len(base) >= 4 and base in hay


def generate_for_alert(
    alert: dict,
    raw_source_text: Optional[str],
    client,
    settings: CareTeamSettings,
    *,
    label_getter: Optional[Callable] = None,
    page_getter: Optional[Callable] = None,
    searcher: Optional[Callable[[str], str]] = None,
    force: bool = False,
) -> dict:
    """Return a care_team result dict. Never raises for a single bad card.

    `client` is anything with `.structured(model=, system=, user=, schema=)`
    returning an object with `.parsed` and `.usage` (the existing
    triage.openai_client.OpenAIClient satisfies this).
    """
    s = alert.get("summary_json") or {}
    paper_text = clean_source_text(raw_source_text)[:PAPER_CHAR_LIMIT]
    base = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.model,
        "version": 2,
    }

    ok, why = check_eligibility(alert, paper_text, settings, force=force)
    if not ok:
        return {**base, "status": "skipped", "reason": why}

    tokens = 0
    try:
        # 1. Drug names → official FDA labels.
        labels: list[DrugLabel] = []
        names: list[str] = []
        label_misses: list[str] = []
        if settings.use_fda_labels:
            dn, _ = _structured(
                client, settings, settings.drug_name_model,
                system=DRUG_NAMES_SYSTEM,
                user=f"Title: {alert.get('title') or ''}\nIntervention: {s.get('intervention') or ''}\nRegimen: {s.get('regimen_description') or ''}",
                schema=DRUG_NAMES_SCHEMA,
            )
            tokens += (dn.usage or {}).get("total_tokens", 0)
            raw_names = list(dn.parsed.get("generic_names") or [])
            names = [n for n in raw_names if _drug_named_in_card(n, alert, paper_text)]
            label_misses = [f"{n} (not named on the card)" for n in raw_names if n not in names]
            ctx = _card_context(alert)
            labels = fetch_labels(names, label_getter, ctx) if label_getter else fetch_labels(names, context=ctx)
            found = {base_ingredient(l.drug) for l in labels}
            label_misses += [f"{n} (no FDA label found)" for n in names if base_ingredient(n) not in found]

        # 2. Extra trial sources, all downloaded and read by code.
        external: dict = {}          # url -> SourceDoc
        excerpts: list[dict] = []
        finder_rejected: list[dict] = []
        ncts = nct_ids_for(alert, paper_text + " " + _card_context(alert))
        if settings.use_registry:
            for nct in ncts:
                doc = fetch_registry(nct, page_getter)
                if doc:
                    external[doc.url] = doc
        if settings.use_web_finder:
            excerpts, pages, finder_rejected = find_verified_excerpts(
                alert, ncts, searcher or default_searcher(settings.finder_model, settings.fallback_model), page_getter)
            external.update(pages)

        # 3. Extract rows with quotes.
        per_label = LABEL_PROMPT_BUDGET // max(1, len(labels))
        blocks = "\n\n".join(l.prompt_block(per_label) for l in labels) if labels else NO_LABELS_BLOCK
        ext_parts = [registry_block(d) for d in external.values() if d.kind == "registry"]
        if excerpts:
            ext_parts.append(excerpts_block(excerpts))
        ext_blocks = "\n\n".join(ext_parts) if ext_parts else NO_EXTERNAL_BLOCK
        user = ROWS_USER_TEMPLATE.format(
            title=alert.get("title") or "",
            journal=s.get("journal") or "",
            population=s.get("population") or "",
            regimen=s.get("regimen_description") or "",
            so_what=s.get("carcinos_one_liner") or "",
            paper_text=paper_text or "(none stored for this card — use the FDA label and other sources below)",
            label_blocks=blocks,
            external_blocks=ext_blocks,
        )
        res, model_used = _structured(client, settings, settings.model,
                                      system=ROWS_SYSTEM, user=user, schema=ROWS_SCHEMA)
        base["model"] = model_used
        tokens += (res.usage or {}).get("total_tokens", 0)

        # 4. Code checks (web/registry quotes are re-checked against the downloaded pages).
        check = validate(res.parsed, paper_text, labels, external)
    except Exception as e:  # one card failing must never stop the run
        log.warning("care-team generation failed for %s: %s", alert.get("id"), e)
        return {**base, "status": "error", "reason": str(e)[:300]}

    out = {
        **base,
        "status": check["status"],
        "labels": [l.to_dict() for l in labels],
        "external_sources": [d.to_dict() for d in external.values()],
        "finder_rejected": finder_rejected[:12],
        # What was looked up and found, so a miss is visible in the admin portal.
        "sources_used": {
            "drugs": names,
            "labels": [l.display_brand + (f" ({l.route})" if l.route and not l.other_formulation else "") for l in labels],
            "label_misses": label_misses,
            "nct_ids": ncts,
            "registry_found": [d.name for d in external.values() if d.kind == "registry"],
            "web_passages": len(excerpts),
        },
        "rows": check["rows"],                 # everything proposed, with checks (editor only)
        "proposed_display": check["display_rows"],
        "tokens": tokens,
        "disclaimer": DISCLAIMER,
    }
    if check["status"] == "omitted":
        out["reason"] = check["omit_reason"]
    return out


def summary_updates(result: dict) -> dict:
    """Keys merged into summary_json.

    care_team_rows is the only thing readers ever see. It holds rows that passed
    every check; the editor can edit or remove them in the admin portal before
    the card is published.
    """
    return {
        "care_team": result,
        "care_team_rows": result.get("proposed_display") if result.get("status") == "ready" else [],
    }
