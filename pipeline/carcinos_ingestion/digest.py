"""
Weekly digest exporter.

Pulls PUBLISHED (or CORRECTED) alerts from Supabase for a rolling window and
writes a standalone, styled HTML digest. Visual identity matches the client-
facing /this-week/ page so the archived file and the live page are visually
identical.

Usage:
  # Default: last 7 days, write to ./digests/carcinos-weekly-<monday>.html
  python -m carcinos_ingestion.digest

  # Custom output path
  python -m carcinos_ingestion.digest --out /Users/me/Documents/Claude/CarcinoS/digests/

  # Custom window (e.g. last 14 days)
  python -m carcinos_ingestion.digest --days 14
"""

from __future__ import annotations
import argparse
import html
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Config


# ---------------------------------------------------------------------------
# Display helpers — must stay in sync with landing/this-week/index.html so the
# archived HTML and the live page look identical.
# ---------------------------------------------------------------------------
SITE_LABEL = {
    "breast": "Breast", "thoracic": "Thoracic", "gastrointestinal": "GI",
    "gu": "GU", "gynecologic": "Gynecologic", "hematologic": "Hematology",
    "cns": "CNS", "head_neck": "Head & Neck", "cutaneous": "Cutaneous",
    "sarcoma": "Sarcoma",
}
TIER_LABEL = {"A": "Practice Impacting", "B": "Incremental", "C": "Horizon"}
TIER_SIGNAL = {"A": "■ ■ ■", "B": "■ ■", "C": "■"}


@dataclass
class FlatAlert:
    """A single alert flattened from alerts + summary_json for rendering."""
    id: str
    tier: str
    disease_site_code: Optional[str]
    title: str
    one_liner: str
    journal: str
    pub_date: str
    evidence_strength: str
    tier_rationale: str
    study_design: str
    effect_size: str
    tags: list[str]
    source_url: str = ""


def _source_url(src0: dict, trial: dict) -> str:
    """Resolve a best-effort source URL from summary_json fields."""
    if src0.get("url"):
        return src0["url"]
    doi = trial.get("doi") or src0.get("doi") or ""
    if doi:
        return doi if doi.startswith("http") else f"https://doi.org/{doi}"
    pmid = src0.get("pmid") or ""
    if pmid:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return ""


def _flatten_alert(row: dict[str, Any]) -> FlatAlert:
    s = row.get("summary_json") or {}
    sources = s.get("sources") or []
    src0 = sources[0] if sources else {}
    trial = s.get("trial") or {}
    site = row.get("disease_sites") or {}
    return FlatAlert(
        id=row["id"],
        tier=row["tier"],
        disease_site_code=site.get("code") if isinstance(site, dict) else None,
        title=row.get("title") or "",
        one_liner=s.get("carcinos_one_liner") or "",
        journal=src0.get("journal") or s.get("journal") or "",
        pub_date=src0.get("publication_date") or s.get("publication_date") or "",
        evidence_strength=s.get("evidence_strength") or "",
        tier_rationale=s.get("tier_rationale") or "",  # admin audit text — not for subscribers
        study_design=s.get("regimen_description") or "",  # human-readable study narrative
        effect_size=(s.get("key_results") or {}).get("effect_size") or "",  # human-readable key finding
        tags=list(s.get("who_should_care") or []),
        source_url=_source_url(src0, trial),
    )


def _monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def fetch_for_user(
    config: Config,
    user_id: str,
    days: int = 7,
    as_of: Optional[date] = None,
) -> tuple[list[FlatAlert], str]:
    """Fetch published alerts for a specific user, applying their scope + site + tier preferences.

    Uses the get_user_feed_for_digest() RPC defined in migration 04_scope_filter.sql.
    Requires the SERVICE_ROLE key (service-side only; never expose to frontend).

    Returns (alerts, oncology_scope) where oncology_scope is 'all_oncology' or
    'radiation_oncology' — used to annotate the personalized digest header.

    Example:
        alerts, scope = fetch_for_user(cfg, user_id='abc-123', days=7)
        html = render_digest(alerts, monday, scope_label=scope)
    """
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase-py not installed. Run: pip install supabase", file=sys.stderr)
        sys.exit(2)

    if not (config.supabase_url and config.supabase_service_role_key):
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set.", file=sys.stderr)
        sys.exit(2)

    sb = create_client(config.supabase_url, config.supabase_service_role_key)
    if as_of is None:
        as_of = date.today()
    since = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=days)

    resp = sb.rpc("get_user_feed_for_digest", {
        "p_user_id": user_id,
        "p_since": since.isoformat(),
    }).execute()

    rows = resp.data or []
    scope = rows[0]["oncology_scope"] if rows else "all_oncology"

    def _flat(row: dict) -> FlatAlert:
        s = row.get("summary_json") or {}
        cls = s.get("classification") or {}
        sources = s.get("sources") or []
        src0 = sources[0] if sources else {}
        trial = s.get("trial") or {}
        return FlatAlert(
            id=str(row["alert_id"]),
            tier=row["tier"],
            disease_site_code=row.get("disease_site_code"),
            title=row.get("title") or "",
            one_liner=s.get("carcinos_one_liner") or "",
            journal=src0.get("journal") or s.get("journal") or "",
            pub_date=src0.get("publication_date") or s.get("publication_date") or "",
            evidence_strength=s.get("evidence_strength") or "",
            tier_rationale=s.get("tier_rationale") or "",  # admin audit text — not for subscribers
            study_design=s.get("regimen_description") or "",  # human-readable study narrative
            effect_size=(s.get("key_results") or {}).get("effect_size") or "",  # human-readable key finding
            tags=list(s.get("who_should_care") or []),
            source_url=_source_url(src0, trial),
        )

    return [_flat(r) for r in rows], scope


def fetch_published(config: Config, days: int = 7, as_of: Optional[date] = None) -> list[FlatAlert]:
    """Fetch PUBLISHED/CORRECTED alerts within the rolling window.

    Uses the service role key because the pipeline runs server-side; the
    same RLS policy that exposes PUBLISHED rows to anon would work but we
    keep parity with the rest of the pipeline."""
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase-py not installed. Run: pip install supabase",
              file=sys.stderr)
        sys.exit(2)

    if not (config.supabase_url and config.supabase_service_role_key):
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set.",
              file=sys.stderr)
        sys.exit(2)

    sb = create_client(config.supabase_url, config.supabase_service_role_key)
    if as_of is None:
        as_of = date.today()
    window_start = (datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
                    - timedelta(days=days))

    res = (
        sb.table("alerts")
          .select("id, tier, status, title, summary_json, disease_sites(code), published_at")
          .in_("status", ["PUBLISHED", "CORRECTED"])
          .gte("published_at", window_start.isoformat())
          .order("published_at", desc=True)
          .execute()
    )
    return [_flatten_alert(row) for row in (res.data or [])]


# ---------------------------------------------------------------------------
# HTML rendering — single self-contained string template.
# ---------------------------------------------------------------------------
_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #060609; --body: #b0b0bc; --white: #ffffff;
  --grey: rgba(255,255,255,0.55); --grey-dim: rgba(255,255,255,0.35);
  --border: rgba(255,255,255,0.10);
  --green: #6ab87a; --green-dim: rgba(106,184,122,0.14);
  --green-border: rgba(106,184,122,0.35);
  --inc-bg: #e2e2e8; --hor-bg: #d8d8de;
}
html, body { background: var(--bg); color: var(--body);
  font-family: -apple-system, "SF Pro Display", "SF Pro", "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.55; -webkit-font-smoothing: antialiased; }
.container { max-width: 880px; margin: 0 auto; padding: 48px 32px 80px; }
header { display: flex; align-items: center; gap: 14px;
  padding-bottom: 28px; border-bottom: 1px solid var(--border); margin-bottom: 36px; }
.logo { width: 44px; height: 44px; border: 1.5px solid rgba(255,255,255,0.6);
  border-radius: 10px; background: rgba(255,255,255,0.04);
  display: flex; align-items: center; justify-content: center;
  font-family: Georgia, serif; font-size: 18px; font-weight: 800;
  color: var(--green); letter-spacing: -0.5px; }
.brand-text { display: flex; flex-direction: column; }
.brand-name { font-size: 22px; font-weight: 700; color: var(--white);
  letter-spacing: -0.4px; line-height: 1.2; }
.brand-name .s { color: var(--green); }
.brand-sub { font-size: 13px; color: var(--grey); margin-top: 2px; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 40px; }
.stat { background: rgba(255,255,255,0.03); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; }
.stat-label { font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 1.1px; color: var(--grey-dim); margin-bottom: 5px; }
.stat-value { font-size: 24px; font-weight: 800; color: var(--white); letter-spacing: -0.6px; }
.stat-value.green { color: var(--green); }
.section-header { margin: 36px 0 18px; padding: 14px 18px; border-radius: 10px;
  display: flex; align-items: center; justify-content: space-between; }
.section-header.pi  { background: var(--green-dim); border: 1px solid var(--green-border); }
.section-header.inc { background: var(--inc-bg); }
.section-header.hor { background: var(--hor-bg); }
.section-title { display: flex; align-items: center; gap: 12px;
  font-size: 15px; font-weight: 700; letter-spacing: -0.2px; }
.section-header.pi .section-title { color: var(--white); }
.section-header.inc .section-title,
.section-header.hor .section-title { color: #1a1a22; }
.signal { font-family: "SF Mono", "Menlo", monospace; font-size: 12px; letter-spacing: 1px; }
.section-header.pi .signal { color: #000; background: rgba(255,255,255,0.85); padding: 2px 7px; border-radius: 4px; }
.section-header.inc .signal, .section-header.hor .signal { color: #000; }
.section-count { font-size: 12px; font-weight: 500; }
.section-header.pi .section-count { color: rgba(255,255,255,0.65); }
.section-header.inc .section-count, .section-header.hor .section-count { color: rgba(0,0,0,0.55); }
.cards { display: flex; flex-direction: column; gap: 10px; }
.card { background: rgba(255,255,255,0.02); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px 18px; }
.card.pi { background: rgba(106,184,122,0.04); border-color: rgba(106,184,122,0.18); }
.card-title { font-size: 15px; font-weight: 700; color: var(--white);
  line-height: 1.4; margin-bottom: 6px; letter-spacing: -0.1px; }
.card-meta { font-size: 12px; color: var(--grey-dim); margin-bottom: 10px; }
.card-meta .dot { padding: 0 6px; opacity: 0.6; }
.card-body { font-size: 13.5px; color: var(--body); line-height: 1.55; margin-bottom: 10px; }
.card-body strong { color: var(--white); font-weight: 600; }
.card-footer { display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px; border-top: 1px solid var(--border);
  padding-top: 10px; font-size: 12px; color: var(--grey-dim); }
.card-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 10.5px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.6px; padding: 3px 7px; border-radius: 4px;
  background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.65); }
.tag.evidence-a { background: var(--green-dim); color: var(--green); }
.card-signal { font-family: "SF Mono", "Menlo", monospace; font-size: 11px;
  letter-spacing: 1.2px; color: var(--white); }
.empty { border: 1px dashed var(--border); border-radius: 12px;
  padding: 28px 24px; text-align: center; color: var(--grey-dim);
  font-size: 13px; }
.empty strong { color: var(--white); font-weight: 600; }
footer { margin-top: 56px; padding-top: 22px; border-top: 1px solid var(--border);
  font-size: 12px; color: var(--grey-dim); line-height: 1.6; }
footer .sig { color: var(--green); font-weight: 600; }
@media (max-width: 640px) {
  .container { padding: 32px 18px 64px; }
  .stats { grid-template-columns: repeat(2, 1fr); }
  .brand-name { font-size: 19px; }
}
"""


def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _render_card(a: FlatAlert) -> str:
    tier_class = "pi" if a.tier == "A" else ""
    evidence_class = "evidence-a" if a.evidence_strength == "A" else ""
    tags_html = "".join(f'<span class="tag">{_esc(t)}</span>' for t in a.tags)
    site_label = SITE_LABEL.get(a.disease_site_code or "", a.disease_site_code or "")
    # one_liner allows editor <strong> tags — keep raw HTML.
    return f'''
    <div class="card {tier_class}">
      <div class="card-title">{_esc(a.title)}</div>
      <div class="card-meta">
        {_esc(a.journal)}<span class="dot">·</span>{_esc(a.study_design)}<span class="dot">·</span>{site_label}
      </div>
      <div class="card-body">{a.one_liner}</div>
      <div class="card-footer">
        <div class="card-tags">
          <span class="tag {evidence_class}">Evidence {_esc(a.evidence_strength) or "?"}</span>
          {tags_html}
        </div>
        <span class="card-signal">{TIER_SIGNAL[a.tier]}</span>
      </div>
    </div>'''


def _render_section(tier: str, items: list[FlatAlert]) -> str:
    header_class = "pi" if tier == "A" else "inc" if tier == "B" else "hor"
    header = f'''
    <div class="section-header {header_class}">
      <div class="section-title">
        <span class="signal">{TIER_SIGNAL[tier]}</span>
        <span>{TIER_LABEL[tier]}</span>
      </div>
      <span class="section-count">{len(items)} finding{"s" if len(items) != 1 else ""}</span>
    </div>'''
    if not items:
        return header + f'<div class="empty">No <strong>{TIER_LABEL[tier]}</strong> findings this week.</div>'
    cards = "".join(_render_card(a) for a in items)
    return header + f'<div class="cards">{cards}</div>'


def render_digest(alerts: list[FlatAlert], monday: date) -> str:
    pi  = [a for a in alerts if a.tier == "A"]
    inc = [a for a in alerts if a.tier == "B"]
    hor = [a for a in alerts if a.tier == "C"]
    # %-d is non-portable (Linux/macOS only); build the label manually so it
    # works on Windows too (e.g., "May 11, 2026" rather than "May 11, 2026").
    week_label = f"{monday.strftime('%B')} {monday.day}, {monday.year}"
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>CarcinoS — Weekly Oncology Digest · Week of {week_label}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">

  <header>
    <div class="logo">CS</div>
    <div class="brand-text">
      <div class="brand-name">Carcino<span class="s">S</span></div>
      <div class="brand-sub">Weekly Oncology Digest · Week of {week_label}</div>
    </div>
  </header>

  <div class="stats">
    <div class="stat"><div class="stat-label">Findings</div><div class="stat-value">{len(alerts)}</div></div>
    <div class="stat"><div class="stat-label">Practice Impacting</div><div class="stat-value green">{len(pi)}</div></div>
    <div class="stat"><div class="stat-label">Incremental</div><div class="stat-value">{len(inc)}</div></div>
    <div class="stat"><div class="stat-label">Horizon</div><div class="stat-value">{len(hor)}</div></div>
  </div>

  {_render_section("A", pi)}
  {_render_section("B", inc)}
  {_render_section("C", hor)}

  <footer>
    <p><span class="sig">CarcinoS</span> — Salient Oncology Intelligence. Generated {date.today().isoformat()}. Sources verified from PubMed and peer-reviewed journals. This digest is a research summary for clinicians; treatment decisions must remain individualized to each patient.</p>
  </footer>

</div>
</body>
</html>
'''


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="carcinos-digest",
        description="Export this week's PUBLISHED alerts to a styled HTML digest.")
    p.add_argument("--days", type=int, default=7,
        help="Lookback window in days (default: 7).")
    p.add_argument("--as-of", default=None,
        help="Date to anchor 'this week' on (YYYY-MM-DD). Defaults to today.")
    p.add_argument("--out", default="digests/",
        help="Output directory or file path. Default: ./digests/")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    cfg = Config.from_env()
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    monday = _monday_of_week(as_of)
    alerts = fetch_published(cfg, days=args.days, as_of=as_of)

    html_doc = render_digest(alerts, monday)

    out_path = Path(args.out)
    if out_path.is_dir() or args.out.endswith("/"):
        out_path.mkdir(parents=True, exist_ok=True)
        out_path = out_path / f"carcinos-weekly-{monday.isoformat()}.html"
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {len(alerts)} alert(s) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
