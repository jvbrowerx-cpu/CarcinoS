"""
Run the care-team step against cards in Supabase.

WRITE (runs automatically at the end of the weekly pipeline; turn off with
CARE_TEAM_ENABLED=false):
    python -m carcinos_ingestion.care_team.run_care_team --write --since-days 2

PREVIEW (optional, from a terminal; writes nothing, produces a report):
    python -m carcinos_ingestion.care_team.run_care_team --preview --since-days 14

Safety:
  * Write mode only touches cards awaiting review or approved but not yet sent
    (EXTRACTED, EDITOR_REVIEW, APPROVED). Published cards are never modified.
  * Existing care-team results are not overwritten unless --force.
  * Only two keys are added to summary_json: care_team and care_team_rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import CareTeamSettings
from .generate import generate_for_alert, summary_updates

log = logging.getLogger("carcinos.care_team.run")


def _supabase():
    from supabase import create_client  # same client the pipeline uses
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def load_cards(sb, since_days: int, tiers: list[str], statuses: list[str] | None, ids: list[str] | None) -> list[dict]:
    q = sb.table("alerts").select("id, tier, status, title, summary_json, created_at, primary_source_id")
    if ids:
        q = q.in_("id", ids)
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        q = q.gte("created_at", since).in_("tier", tiers)
        if statuses:
            q = q.in_("status", statuses)
    return q.order("created_at", desc=True).execute().data or []


def load_source_text(sb, alert: dict) -> str | None:
    srcs = (alert.get("summary_json") or {}).get("sources") or []
    sid = alert.get("primary_source_id") or (srcs[0].get("source_id") if srcs else None)
    if not sid:
        return None
    rows = sb.table("sources").select("raw_text").eq("id", sid).limit(1).execute().data
    return rows[0].get("raw_text") if rows else None


def write_report(results: list[tuple[dict, dict]], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "care_team_preview.json").write_text(json.dumps(
        [{"id": a["id"], "title": a.get("title"), "result": r} for a, r in results], indent=2))
    lines = ["# Care Team — preview (nothing was saved)", ""]
    for alert, r in results:
        s = alert.get("summary_json") or {}
        lines += [f"## {alert.get('title')}", f"*{s.get('journal') or ''} · tier {alert.get('tier')} · {alert.get('status')}*",
                  "", f"**Status:** `{r.get('status')}` {r.get('reason') or ''}", ""]
        for row in r.get("rows", []):
            mark = "✓ shown" if row.get("passed") else "✗ removed"
            lines.append(f"- **{row.get('field')}** ({mark}): {row.get('text')}")
            for ev in row.get("evidence", []):
                lines.append(f"    - {'✓' if ev.get('verified') else '✗'} [{ev.get('source')}] “{ev.get('quote')}”")
            for iss in row.get("issues", []):
                lines.append(f"    - ⚠ {iss}")
        lines.append("\n---")
    (out / "care_team_preview.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="Generate and report only. No database writes.")
    mode.add_argument("--write", action="store_true", help="Save results to new, unreviewed cards.")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--ids", default="", help="Comma-separated alert ids (overrides --since-days).")
    p.add_argument("--out", default="care_team_report")
    p.add_argument("--force", action="store_true", help="Recompute even if a result already exists.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = CareTeamSettings()

    from ..triage.openai_client import OpenAIClient  # existing wrapper, unchanged
    client = OpenAIClient()
    sb = _supabase()
    ids = [x for x in args.ids.split(",") if x.strip()] or None

    if args.preview:
        cards = load_cards(sb, args.since_days, settings.tiers, None, ids)
        results = [(a, generate_for_alert(a, load_source_text(sb, a), client, settings, force=True)) for a in cards]
        write_report(results, Path(args.out))
        log.info("preview written to %s/ (%d cards)", args.out, len(cards))
        return 0

    if not settings.enabled:
        log.info("CARE_TEAM_ENABLED=false — care-team step is off. Nothing written.")
        return 0
    cards = load_cards(sb, args.since_days, settings.tiers, settings.writable_statuses, ids)
    written = 0
    for a in cards:
        if a.get("status") not in settings.writable_statuses:
            continue  # belt and braces: never touch published cards
        r = generate_for_alert(a, load_source_text(sb, a), client, settings, force=args.force)
        if r["status"] == "skipped":
            continue
        if a.get("status") == "APPROVED":
            r["added_after_approval"] = True   # flagged in the admin portal for a quick look
        merged = {**(a.get("summary_json") or {}), **summary_updates(r)}
        sb.table("alerts").update({"summary_json": merged}).eq("id", a["id"]).execute()
        written += 1
        log.info("%s → %s (%d rows shown)", a["id"], r["status"], len(merged.get("care_team_rows") or []))
    log.info("care-team step finished: %d cards updated", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
