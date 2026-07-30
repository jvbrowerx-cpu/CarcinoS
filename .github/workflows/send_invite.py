"""
CarcinoS — One-time invite script for existing subscribers.

Sends a personalized email to all verified subscribers telling them to create
a CarcinoS account (email + password) to continue accessing the weekly digest.

Usage:
  python send_invite.py                  # live send
  python send_invite.py --dry-run        # preview without sending

Environment variables required (same as deliver.py):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  RESEND_API_KEY
  CARCINOS_FROM_EMAIL   (default: CarcinoS <digest@carcino-s.com>)
"""

from __future__ import annotations
import argparse
import os
import sys

# ── Dependencies ──────────────────────────────────────────────────────────────
try:
    from supabase import create_client
except ImportError:
    print("ERROR: supabase-py not installed. Run: pip install supabase", file=sys.stderr)
    sys.exit(1)

try:
    import resend
except ImportError:
    print("ERROR: resend not installed. Run: pip install resend", file=sys.stderr)
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
SIGNUP_URL   = "https://carcino-s.com/this-week/"
FROM_DEFAULT = "CarcinoS <digest@carcino-s.com>"

# ── Email template ────────────────────────────────────────────────────────────
def build_invite_html(email: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>CarcinoS — Create your account</title>
</head>
<body style="margin:0;padding:0;background:#060609;font-family:-apple-system,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#060609;padding:40px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr><td style="padding-bottom:28px;">
        <table cellpadding="0" cellspacing="0">
          <tr>
            <td style="border:1.5px solid rgba(255,255,255,0.6);border-radius:8px;width:34px;height:34px;text-align:center;vertical-align:middle;background:rgba(255,255,255,0.04);">
              <span style="font-family:Georgia,serif;font-size:14px;font-weight:800;color:#fff;letter-spacing:-0.4px;">C<span style="color:#72a37a;">S</span></span>
            </td>
            <td style="padding-left:12px;font-size:17px;font-weight:700;color:#fff;letter-spacing:-0.3px;">
              Carcino<span style="color:#72a37a;">S</span>
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- Card -->
      <tr><td style="background:#0e0e14;border:1px solid rgba(255,255,255,0.10);border-radius:14px;padding:36px 36px 32px;">

        <p style="margin:0 0 8px;font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:#72a37a;">
          Action required
        </p>
        <h1 style="margin:0 0 16px;font-size:24px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;">
          Set up your CarcinoS account
        </h1>
        <p style="margin:0 0 20px;font-size:15px;color:#b0b0bc;line-height:1.6;">
          CarcinoS now has a member portal with full weekly digest access and oncologist discussion threads.
          To continue receiving and reading your weekly updates, please create a free account using your
          email address below.
        </p>

        <!-- Email pill -->
        <table cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
          <tr>
            <td style="background:rgba(114,163,122,0.12);border:1px solid rgba(114,163,122,0.3);border-radius:6px;padding:8px 16px;font-size:13px;font-weight:600;color:#72a37a;">
              {email}
            </td>
          </tr>
        </table>

        <p style="margin:0 0 24px;font-size:14px;color:#b0b0bc;line-height:1.6;">
          Use the button below to go to the CarcinoS portal and create your account.
          Use <strong style="color:#ffffff;">{email}</strong> as your email and choose a password.
          Your disease site and delivery preferences are already saved.
        </p>

        <!-- CTA button -->
        <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
          <tr>
            <td style="background:#72a37a;border-radius:9px;">
              <a href="{SIGNUP_URL}" style="display:inline-block;padding:14px 32px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;letter-spacing:-0.2px;">
                Create my account →
              </a>
            </td>
          </tr>
        </table>

        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.35);line-height:1.6;">
          This is a one-time setup. Once your account is created your weekly digest will continue
          as normal — plus you'll be able to discuss findings with other oncologists on the portal.
        </p>

      </td></tr>

      <!-- Footer -->
      <tr><td style="padding-top:24px;font-size:11px;color:rgba(255,255,255,0.25);line-height:1.7;text-align:center;">
        <p style="margin:0;">CarcinoS LLC · Salient Oncology Intelligence</p>
        <p style="margin:4px 0 0;">
          You're receiving this because you subscribed to the CarcinoS weekly digest.
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Send CarcinoS account invite to existing subscribers.")
    parser.add_argument("--dry-run", action="store_true", help="Print emails without sending")
    args = parser.parse_args()
    dry_run = args.dry_run

    # Env vars
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    resend_key   = os.getenv("RESEND_API_KEY", "")
    from_email   = os.getenv("CARCINOS_FROM_EMAIL", FROM_DEFAULT)

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.", file=sys.stderr)
        sys.exit(1)
    if not resend_key and not dry_run:
        print("ERROR: RESEND_API_KEY must be set (or use --dry-run).", file=sys.stderr)
        sys.exit(1)

    # Pull verified subscribers
    sb = create_client(supabase_url, supabase_key)
    resp = (
        sb.table("users")
        .select("id, email")
        .eq("verified", True)
        .in_("delivery", ["email", "both"])
        .execute()
    )
    subscribers = resp.data or []

    if not subscribers:
        print("No verified subscribers found.")
        return

    print(f"Found {len(subscribers)} subscriber(s). {'[DRY RUN] ' if dry_run else ''}Sending invites...\n")

    resend.api_key = resend_key
    sent = 0
    failed = 0

    for user in subscribers:
        email = user.get("email", "").strip()
        if not email:
            continue

        subject  = "CarcinoS — Set up your account to continue accessing the digest"
        html     = build_invite_html(email)

        if dry_run:
            print(f"  [DRY RUN] Would send to: {email}")
            sent += 1
            continue

        try:
            result = resend.Emails.send({
                "from":    from_email,
                "to":      [email],
                "subject": subject,
                "html":    html,
            })
            print(f"  [SENT] {email} — id: {result.get('id', '?')}")
            sent += 1
        except Exception as e:
            print(f"  [FAILED] {email} — {e}")
            failed += 1

    print(f"\nDone. {sent} sent, {failed} failed.")


if __name__ == "__main__":
    main()
