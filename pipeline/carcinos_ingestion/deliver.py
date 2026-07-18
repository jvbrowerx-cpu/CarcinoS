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
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: #060609; color: #b0b0bc;
  font-family: -apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.55;
}
.wrapper { max-width: 640px; margin: 0 auto; padding: 32px 24px 60px; }
.header {
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 24px; border-bottom: 1px solid rgba(255,255,255,0.1);
  margin-bottom: 28px;
}
.logo {
  width: 40px; height: 40px; border: 1.5px solid rgba(255,255,255,0.5);
  border-radius: 9px; background: rgba(255,255,255,0.04);
  display: inline-flex; align-items: center; justify-content: center;
  font-family: Georgia, serif; font-size: 16px; font-weight: 800;
  color: #6ab87a; text-decoration: none;
}
.brand-name { font-size: 20px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
.brand-name .s { color: #6ab87a; }
.brand-sub { font-size: 12px; color: rgba(255,255,255,0.45); margin-top: 2px; }
.scope-note {
  font-size: 12px; color: rgba(255,255,255,0.35);
  background: rgba(122,142,122,0.08); border: 1px solid rgba(122,142,122,0.25);
  border-radius: 8px; padding: 8px 14px; margin-bottom: 24px; line-height: 1.5;
}
.section-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px;
  color: rgba(255,255,255,0.35); margin: 28px 0 12px;
}
.card {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.09);
  border-radius: 10px; padding: 16px 18px; margin-bottom: 10px;
}
.card.pi { background: rgba(106,184,122,0.05); border-color: rgba(106,184,122,0.2); }
.card-site {
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;
  color: rgba(255,255,255,0.3); margin-bottom: 5px;
}
.card-title {
  font-size: 15px; font-weight: 700; color: #fff;
  line-height: 1.4; margin-bottom: 7px; letter-spacing: -0.1px;
}
.card-meta { font-size: 11px; color: rgba(255,255,255,0.3); margin-bottom: 9px; }
.card-meta .dot { padding: 0 5px; }
.card-body { font-size: 13.5px; color: #b0b0bc; line-height: 1.55; }
.card-source { margin-top: 10px; }
.card-source a {
  font-size: 12px; font-weight: 700; color: #6ab87a; text-decoration: none;
  letter-spacing: 0.2px;
}
.empty {
  text-align: center; padding: 24px; color: rgba(255,255,255,0.3);
  font-size: 13px; border: 1px dashed rgba(255,255,255,0.08);
  border-radius: 10px;
}
.footer {
  margin-top: 44px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,0.07);
  font-size: 11px; color: rgba(255,255,255,0.25); line-height: 1.7;
}
.footer a { color: rgba(122,142,122,0.8); text-decoration: none; }
"""


def _esc(s: Any) -> str:
    import html
    return html.escape(str(s or ""), quote=True)


def build_email_html(
    alerts: list,
    scope: str,
    week_label: str,
    unsubscribe_url: str = "https://carcino-s.com/settings",
) -> str:
    scope_note = (
        "Radiation Oncology scope — showing only alerts with direct or indirect radiation oncology relevance."
        if scope == "radiation_oncology"
        else "All Oncology scope — showing all tiers across your selected disease sites."
    )

    pi  = [a for a in alerts if a.tier == "A"]
    inc = [a for a in alerts if a.tier == "B"]
    hor = [a for a in alerts if a.tier == "C"]

    def _section(tier: str, items: list) -> str:
        if not items:
            return ""
        label = TIER_LABEL[tier]
        signal = TIER_SIGNAL[tier]
        cards = ""
        for a in items:
            site_label = SITE_LABEL.get(a.disease_site_code or "", a.disease_site_code or "")
            tier_class = "pi" if tier == "A" else ""
            source_link = (
                f'<div class="card-source"><a href="{_esc(a.source_url)}" target="_blank" rel="noopener">↗ Read paper</a></div>'
                if a.source_url else ""
            )
            cards += f"""
            <div class="card {tier_class}">
              <div class="card-site">{_esc(site_label)}</div>
              <div class="card-title">{_esc(a.title)}</div>
              <div class="card-meta">
                {_esc(a.journal)}<span class="dot">·</span>{_esc(a.pub_date)}<span class="dot">·</span>{signal}
              </div>
              <div class="card-body">{a.one_liner}</div>
              {source_link}
            </div>"""
        return f'<div class="section-label">{_esc(label)}</div>{cards}'

    body = _section("A", pi) + _section("B", inc) + _section("C", hor)
    if not body:
        body = '<div class="empty">No new updates matched your preferences this week.</div>'

    total = len(alerts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CarcinoS — Weekly Digest · {_esc(week_label)}</title>
<style>{_EMAIL_CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <span class="logo">CS</span>
    <div>
      <div class="brand-name">Carcino<span class="s">S</span></div>
      <div class="brand-sub">Weekly Digest · {_esc(week_label)} · {total} update{"s" if total != 1 else ""}</div>
    </div>
  </div>
  <div class="scope-note">{_esc(scope_note)}</div>
  {body}
  <div class="footer">
    <p>You're receiving this because you signed up for CarcinoS early access.<br/>
    <a href="{_esc(unsubscribe_url)}">Manage preferences</a> · <a href="{_esc(unsubscribe_url)}">Unsubscribe</a></p>
    <p style="margin-top:8px;">CarcinoS · Salient Oncology Intelligence · carcino-s.com</p>
    <p style="margin-top:12px; padding-top:12px; border-top:1px solid rgba(255,255,255,0.05); font-size:10px; color:rgba(255,255,255,0.2);">
      <a href="https://carcino-s.com/tos/">Terms of Service</a> &nbsp;|&nbsp;
      <a href="https://carcino-s.com/privacy/">Privacy Policy</a> &nbsp;|&nbsp;
      <a href="https://carcino-s.com/disclaimer/">Medical Disclaimer</a>
    </p>
  </div>
</div>
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
            html_body = build_email_html(alerts, scope, week_label)
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
