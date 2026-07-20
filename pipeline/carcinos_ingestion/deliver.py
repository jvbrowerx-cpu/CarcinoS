"""
CarcinoS Weekly Delivery Script.

Runs every Sunday night (via GitHub Actions). For each opted-in subscriber:
  1. Calls get_user_feed_for_digest() to get their scoped, filtered alert list
  2. Sends via Resend (email) if delivery in ('email', 'both')
  3. Sends via Expo Push API (push) if delivery in ('push', 'both') and push_token set

Environment variables required:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  RESEND_API_KEY               — from resend.com
  CARCINOS_FROM_EMAIL          — e.g. "CarcinoS <digest@carcino-s.com>"

Usage:
  python -m carcinos_ingestion.deliver
  python -m carcinos_ingestion.deliver --days 14
  python -m carcinos_ingestion.deliver --dry-run
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.error
import textwrap
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .config import Config
from .digest import fetch_for_user, SITE_LABEL, TIER_LABEL, TIER_SIGNAL


# ---------------------------------------------------------------------------
# HTML email template
# ---------------------------------------------------------------------------

_EMAIL_CSS = """
body, table, td { margin:0; padding:0; border:0; }
body { background-color:#060609; }
"""


def _esc(s: Any) -> str:
    import html
    return html.escape(str(s or ""), quote=True)


def _safe_text(s: str) -> str:
    """Escape and append ellipsis if the text appears mid-sentence truncated."""
    s = (s or "").strip()
    if s and s[-1] not in ".!?)\"'":
        s = s + "…"
    return _esc(s)


def build_email_html(
    alerts: list,
    scope: str,
    week_label: str,
    unsubscribe_url: str = "https://carcino-s.com/settings",
    papers_scanned: int = 0,
) -> str:
    scope_note = (
        "Radiation Oncology scope — showing only alerts with direct or indirect radiation oncology relevance."
        if scope == "radiation_oncology"
        else "All Oncology scope — showing all tiers across your selected disease sites."
    )

    pi  = [a for a in alerts if a.tier == "A"]
    inc = [a for a in alerts if a.tier == "B"]
    hor = [a for a in alerts if a.tier == "C"]

    # tier: (label, card_bg, card_border, header_bg, header_text, text_dark, text_mid, text_muted, badge_color)
    TIER_CARD = {
        "A": ("Practice Impacting", "#ffffff", "1px solid #d8e8d8", "#7a9e7d", "#ffffff", "#1a1a1a", "#333333", "#888888", "#3a6a3a"),
        "B": ("Incremental",        "#ffffff", "1px solid #d0d8e8", "#5b7a9e", "#ffffff", "#1a1a1a", "#333333", "#888888", "#2e4a8a"),
        "C": ("Horizon",            "#ffffff", "1px solid #e0d8ee", "#7b6a9e", "#ffffff", "#1a1a1a", "#333333", "#888888", "#5a3a8a"),
    }
    TIER_SQUARES = {"A": "&#9632;&nbsp;&#9632;&nbsp;&#9632;", "B": "&#9632;&nbsp;&#9632;", "C": "&#9632;"}

    def _card(a, tier: str) -> str:
        label, card_bg, card_border, header_bg, header_text, text_dark, text_mid, text_muted, badge_color = TIER_CARD[tier]
        site_label = SITE_LABEL.get(a.disease_site_code or "", a.disease_site_code or "").upper()

        # Journal / Date line
        meta_parts = []
        if a.journal:
            meta_parts.append(f'<strong style="color:{text_dark};font-family:Helvetica,Arial,sans-serif;">Journal:</strong> <em>{_esc(a.journal)}</em>')
        if a.pub_date:
            meta_parts.append(f'<strong style="color:{text_dark};font-family:Helvetica,Arial,sans-serif;">Date:</strong> {_esc(a.pub_date)}')
        meta_line = ' &nbsp;&middot;&nbsp; '.join(meta_parts)

        # Study / regimen — regimen_description is the human-readable narrative from the LLM
        study_display = _safe_text(a.study_design) if a.study_design else '<em style="color:{muted};">See full paper</em>'.format(muted=text_muted)
        study_row = f"""
              <tr><td style="padding-bottom:10px;">
                <p style="margin:0;font-size:13px;color:{text_mid};font-family:Helvetica,Arial,sans-serif;line-height:1.6;"><strong style="color:{text_dark};">Study / regimen:</strong> {study_display}</p>
              </td></tr>"""

        # Key findings — effect_size is the human-readable finding sentence from the LLM
        key_findings_text = a.effect_size or ""
        key_display = _safe_text(key_findings_text) if key_findings_text else '<em style="color:{muted};">See full paper</em>'.format(muted=text_muted)
        findings_row = f"""
              <tr><td style="padding-bottom:10px;">
                <p style="margin:0;font-size:13px;color:{text_dark};font-family:Helvetica,Arial,sans-serif;line-height:1.6;font-weight:600;"><strong>Key findings:</strong> {key_display}</p>
              </td></tr>"""

        # So what / clinical implication — always shown
        one_liner_display = _safe_text(a.one_liner) if a.one_liner else '<em style="color:{muted};">See full paper</em>'.format(muted=text_muted)
        one_liner_row = f"""
              <tr><td style="padding-bottom:14px;">
                <p style="margin:0;font-size:13px;color:{text_mid};font-family:Helvetica,Arial,sans-serif;line-height:1.6;"><strong style="color:{text_dark};">So what (clinical implication):</strong> {one_liner_display}</p>
              </td></tr>"""

        # Divider + bottom row
        evidence_cell = ""
        if a.evidence_strength:
            ev = _esc(a.evidence_strength.upper())
            evidence_cell = f'<td style="vertical-align:middle;"><span style="font-size:10px;font-weight:700;letter-spacing:0.5px;color:{badge_color};border:1px solid {badge_color};border-radius:4px;padding:3px 8px;font-family:Helvetica,Arial,sans-serif;">EVIDENCE {ev}</span></td>'

        source_cell = ""
        if a.source_url:
            source_cell = f'<td align="right" style="vertical-align:middle;"><a href="{_esc(a.source_url)}" style="font-size:12px;font-weight:700;color:{text_dark};text-decoration:none;font-family:Helvetica,Arial,sans-serif;">&#8599; Read paper &nbsp;&#9632;&nbsp;&#9632;&nbsp;&#9632;</a></td>'

        bottom_row = ""
        if evidence_cell or source_cell:
            bottom_row = f"""
              <tr><td style="padding-top:2px;border-top:1px solid rgba(0,0,0,0.1);">
                <table width="100%" cellpadding="0" cellspacing="0" style="padding-top:10px;"><tr>{evidence_cell}{source_cell}</tr></table>
              </td></tr>"""

        return f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="background:{card_bg};border:{card_border};border-radius:10px;margin-bottom:10px;">
          <tr><td style="padding:16px 18px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr><td style="font-size:11px;color:{text_muted};padding-bottom:8px;font-family:Helvetica,Arial,sans-serif;">{meta_line}</td></tr>
              <tr><td style="font-size:15px;font-weight:700;color:{text_dark};line-height:1.4;padding-bottom:12px;font-family:Helvetica,Arial,sans-serif;"><strong>Title:</strong> {_esc(a.title)}</td></tr>
              {study_row}
              {findings_row}
              {one_liner_row}
              {bottom_row}
            </table>
          </td></tr>
        </table>"""

    def _section(tier: str, items: list) -> str:
        if not items:
            return ""
        label = TIER_LABEL[tier]
        _, _, _, header_bg, header_text, _, _, _, _ = TIER_CARD[tier]
        squares = TIER_SQUARES[tier]
        count = len(items)
        cards = "".join(_card(a, tier) for a in items)
        return f"""
        <tr><td style="padding-top:24px;padding-bottom:10px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:{header_bg};border-radius:8px;">
            <tr><td style="padding:13px 16px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="vertical-align:middle;">
                    <span style="font-size:9px;color:rgba(255,255,255,0.4);margin-right:8px;">{squares}</span>
                    <span style="font-size:13px;font-weight:700;color:{header_text};letter-spacing:0.3px;font-family:Helvetica,Arial,sans-serif;">{_esc(label)}</span>
                  </td>
                  <td align="right" style="vertical-align:middle;font-size:12px;color:rgba(255,255,255,0.6);font-family:Helvetica,Arial,sans-serif;">{count} finding{"s" if count != 1 else ""}</td>
                </tr>
              </table>
            </td></tr>
          </table>
        </td></tr>
        <tr><td>{cards}</td></tr>"""

    body_rows = _section("A", pi) + _section("B", inc) + _section("C", hor)
    if not body_rows:
        body_rows = '<tr><td style="text-align:center;padding:24px;color:rgba(255,255,255,0.3);font-size:13px;border:1px dashed rgba(255,255,255,0.08);border-radius:10px;">No new updates matched your preferences this week.</td></tr>'

    total = len(alerts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>CarcinoS Weekly Digest &middot; {_esc(week_label)}</title>
  <style>{_EMAIL_CSS}</style>
</head>
<body style="background-color:#060609;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#060609;">
<tr><td align="center" style="padding:32px 16px 60px;">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

  <!-- HEADER -->
  <tr><td style="padding-bottom:24px;border-bottom:1px solid rgba(255,255,255,0.1);">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="48" valign="middle">
          <div style="width:40px;height:40px;border:1.5px solid rgba(255,255,255,0.5);border-radius:9px;background:rgba(255,255,255,0.04);text-align:center;line-height:40px;font-family:Georgia,serif;font-size:15px;font-weight:800;color:#72a37a;">CS</div>
        </td>
        <td valign="middle" style="padding-left:12px;">
          <p style="margin:0;font-size:20px;font-weight:700;color:#ffffff;font-family:Helvetica,Arial,sans-serif;letter-spacing:-0.3px;">Carcino<span style="color:#72a37a;">S</span></p>
          <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.45);font-family:Helvetica,Arial,sans-serif;">Weekly Digest &middot; {_esc(week_label)} &middot; {total} update{"s" if total != 1 else ""}</p>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- CTA BANNER -->
  <tr><td style="padding:20px 0 4px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(114,163,122,0.08);border:1px solid rgba(114,163,122,0.25);border-radius:8px;">
      <tr><td style="padding:12px 18px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="font-size:12px;color:rgba(255,255,255,0.5);font-family:Helvetica,Arial,sans-serif;">View the full interactive digest online</td>
            <td align="right">
              <a href="https://carcino-s.com/this-week" style="font-size:12px;font-weight:700;color:#72a37a;text-decoration:none;font-family:Helvetica,Arial,sans-serif;">Open this week &#8599;</a>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </td></tr>

  <!-- SCOPE NOTE -->
  <tr><td style="padding:14px 0 0;">
    <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.35);font-family:Helvetica,Arial,sans-serif;line-height:1.5;">{_esc(scope_note)}</p>
  </td></tr>

  <!-- ARTICLES -->
  {body_rows}

  <!-- FOOTER -->
  <tr><td style="padding-top:44px;border-top:1px solid rgba(255,255,255,0.07);margin-top:44px;">
    {f'<p style="margin:0 0 10px;font-size:11px;color:rgba(255,255,255,0.3);font-family:Helvetica,Arial,sans-serif;letter-spacing:0.2px;">{papers_scanned:,} papers scanned this week &middot; {total} selected</p>' if papers_scanned > 0 else ''}
    <p style="margin:0 0 6px;font-size:11px;color:rgba(255,255,255,0.25);font-family:Helvetica,Arial,sans-serif;line-height:1.7;">
      You're receiving this because you signed up for CarcinoS early access.<br/>
      <a href="{_esc(unsubscribe_url)}" style="color:rgba(114,163,122,0.8);text-decoration:none;">Manage preferences</a>
      &nbsp;&middot;&nbsp;
      <a href="{_esc(unsubscribe_url)}" style="color:rgba(114,163,122,0.8);text-decoration:none;">Unsubscribe</a>
    </p>
    <p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.2);font-family:Helvetica,Arial,sans-serif;">
      CarcinoS &middot; Salient Oncology Intelligence &middot; carcino-s.com
    </p>
    <p style="margin:12px 0 0;padding-top:12px;border-top:1px solid rgba(255,255,255,0.05);font-size:10px;color:rgba(255,255,255,0.2);font-family:Helvetica,Arial,sans-serif;">
      <a href="https://carcino-s.com/tos/" style="color:rgba(255,255,255,0.2);text-decoration:none;">Terms of Service</a>
      &nbsp;|&nbsp;
      <a href="https://carcino-s.com/privacy/" style="color:rgba(255,255,255,0.2);text-decoration:none;">Privacy Policy</a>
      &nbsp;|&nbsp;
      <a href="https://carcino-s.com/disclaimer/" style="color:rgba(255,255,255,0.2);text-decoration:none;">Medical Disclaimer</a>
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def build_push_messages(alerts: list, scope: str) -> list[dict]:
    """Build Expo push message objects — one per alert, Tier A only for push
    (to avoid overwhelming users; all tiers go in the email digest)."""
    pi = [a for a in alerts if a.tier == "A"]
    if not pi:
        # Send a single summary push if no Tier A but there are other alerts
        if alerts:
            return [{
                "title": "CarcinoS Weekly Update",
                "body": f"{len(alerts)} new oncology update{'s' if len(alerts) != 1 else ''} in your digest.",
                "data": {"type": "weekly_summary"},
            }]
        return []

    messages = []
    for a in pi[:3]:  # Cap at 3 push notifications per week
        site_label = SITE_LABEL.get(a.disease_site_code or "", "")
        title = f"[{site_label}] Practice Impacting" if site_label else "Practice Impacting Update"
        body = (a.one_liner or a.title or "")[:200]
        messages.append({
            "title": title,
            "body": body,
            "data": {"type": "alert", "tier": "A"},
        })
    return messages


# ---------------------------------------------------------------------------
# Sending helpers
# ---------------------------------------------------------------------------

def send_email(
    resend_api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    html_body: str,
    dry_run: bool = False,
) -> bool:
    """Send via Resend SDK. Returns True on success."""
    if dry_run:
        print(f"    [DRY RUN] Would email → {to_email}: {subject}")
        return True
    try:
        import resend
        resend.api_key = resend_api_key
        params = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        email = resend.Emails.send(params)
        print(f"    [EMAIL SENT] {to_email} — id: {email.get('id', '?')}")
        return True
    except Exception as e:
        print(f"    [EMAIL ERROR] {to_email}: {e}", file=sys.stderr)
        return False


def send_push(
    push_token: str,
    messages: list[dict],
    dry_run: bool = False,
) -> bool:
    """Send via Expo Push API. Returns True on success."""
    if not messages:
        return True
    if dry_run:
        print(f"    [DRY RUN] Would push → {push_token[:30]}… ({len(messages)} message(s))")
        return True
    try:
        import urllib.request
        payloads = [{"to": push_token, **msg} for msg in messages]
        data = json.dumps(payloads).encode()
        req = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"    [PUSH ERROR] {push_token[:30]}…: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main delivery loop
# ---------------------------------------------------------------------------

def run_delivery(config: Config, days: int = 7, dry_run: bool = False) -> dict:
    """
    Fetch all opted-in subscribers, pull their filtered alert feeds, and deliver.

    Returns a summary dict with counts for logging.
    """
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase-py not installed.", file=sys.stderr)
        sys.exit(2)

    if not (config.supabase_url and config.supabase_service_role_key):
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set.", file=sys.stderr)
        sys.exit(2)

    resend_key  = os.getenv("RESEND_API_KEY", "")
    from_email  = os.getenv("CARCINOS_FROM_EMAIL", "CarcinoS <digest@carcino-s.com>")

    sb = create_client(config.supabase_url, config.supabase_service_role_key)

    # Fetch all verified subscribers who want email or push delivery.
    # verified = false (the default) means the user signed up but has not yet
    # been activated — they will not receive digests until verified is set to
    # true in Supabase Studio (Table Editor → users → edit row).
    resp = sb.table("users") \
        .select("id, email, delivery, push_token") \
        .in_("delivery", ["email", "push", "both"]) \
        .eq("verified", True) \
        .execute()

    subscribers = resp.data or []
    print(f"Delivery run: {len(subscribers)} subscriber(s), days={days}, dry_run={dry_run}")

    as_of = date.today()
    monday = as_of - timedelta(days=as_of.weekday())
    week_label = f"{monday.strftime('%B')} {monday.day}, {monday.year}"

    stats = {"total": len(subscribers), "email_sent": 0, "push_sent": 0, "skipped": 0, "errors": 0}

    # Fetch this week's scan count from pipeline_runs (non-critical: silently skip if absent)
    papers_scanned = 0
    try:
        run_row = sb.table("pipeline_runs") \
            .select("stats_json") \
            .order("run_date", desc=True) \
            .limit(1) \
            .single() \
            .execute()
        if run_row.data:
            papers_scanned = run_row.data.get("stats_json", {}).get("papers_fetched", 0) or 0
    except Exception:
        pass  # non-critical

    for sub in subscribers:
        user_id  = sub["id"]
        email    = sub["email"]
        delivery = sub.get("delivery", "email")
        token    = sub.get("push_token")

        print(f"  → {email} | delivery={delivery}")

        try:
            alerts, scope = fetch_for_user(config, user_id=user_id, days=days, as_of=as_of)
        except Exception as e:
            print(f"    [ERROR] fetch_for_user failed: {e}", file=sys.stderr)
            stats["errors"] += 1
            continue

        if not alerts:
            print(f"    No alerts this week — skipping")
            stats["skipped"] += 1
            continue

        print(f"    {len(alerts)} alert(s) | scope={scope}")

        # EMAIL
        if delivery in ("email", "both") and resend_key:
            html_body = build_email_html(alerts, scope, week_label, papers_scanned=papers_scanned)
            subject   = f"CarcinoS — {len(alerts)} new oncology update{'s' if len(alerts) != 1 else ''} · {week_label}"
            ok = send_email(resend_key, from_email, email, subject, html_body, dry_run=dry_run)
            if ok:
                stats["email_sent"] += 1

        # PUSH
        if delivery in ("push", "both") and token:
            messages = build_push_messages(alerts, scope)
            ok = send_push(token, messages, dry_run=dry_run)
            if ok:
                stats["push_sent"] += 1

    print(f"\nDelivery complete: {stats}")
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="carcinos-deliver",
        description="Send weekly CarcinoS digest via email (Resend) and push (Expo).",
    )
    p.add_argument("--days", type=int, default=7,
        help="Lookback window in days (default 7).")
    p.add_argument("--dry-run", action="store_true",
        help="Print what would be sent without actually sending.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    cfg  = Config.from_env()
    run_delivery(cfg, days=args.days, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
