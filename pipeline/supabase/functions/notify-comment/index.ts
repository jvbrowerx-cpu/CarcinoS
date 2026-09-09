/**
 * CarcinoS — Comment Notification Edge Function
 *
 * Triggered by a Supabase Database Webhook on INSERT to the comments table.
 * For each new comment:
 *   1. Calls get_comment_notification_recipients() to find who to notify
 *   2. Sends each recipient a personalised email via Resend
 *
 * Environment variables (set in Supabase Dashboard → Edge Functions → Secrets):
 *   SUPABASE_URL              — your project URL
 *   SUPABASE_SERVICE_ROLE_KEY — service role key (for RPC call)
 *   RESEND_API_KEY            — from resend.com
 *   CARCINOS_FROM_EMAIL       — e.g. "CarcinoS <digest@carcino-s.com>"
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const FROM_EMAIL =
  Deno.env.get("CARCINOS_FROM_EMAIL") ?? "CarcinoS <digest@carcino-s.com>";
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_ROLE_KEY =
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// ── Email template ────────────────────────────────────────────────────────────

function buildEmail(opts: {
  recipientName: string;
  commenterName: string;
  alertTitle: string;
  alertId: string;
  commentSnippet: string;
}): string {
  const portalUrl = `https://carcino-s.com/this-week/`;
  const snippet =
    opts.commentSnippet.length > 200
      ? opts.commentSnippet.slice(0, 197) + "…"
      : opts.commentSnippet;

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>New comment on CarcinoS</title>
</head>
<body style="margin:0;padding:0;background:#060609;font-family:-apple-system,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#060609;padding:40px 16px;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

      <!-- Header -->
      <tr><td style="padding-bottom:28px;">
        <table cellpadding="0" cellspacing="0"><tr>
          <td style="border:1.5px solid rgba(255,255,255,0.6);border-radius:8px;width:34px;height:34px;text-align:center;vertical-align:middle;background:rgba(255,255,255,0.04);">
            <span style="font-family:Georgia,serif;font-size:14px;font-weight:800;color:#fff;">C<span style="color:#72a37a;">S</span></span>
          </td>
          <td style="padding-left:12px;font-size:17px;font-weight:700;color:#fff;letter-spacing:-0.3px;">
            Carcino<span style="color:#72a37a;">S</span>
          </td>
        </tr></table>
      </td></tr>

      <!-- Card -->
      <tr><td style="background:#0e0e14;border:1px solid rgba(255,255,255,0.10);border-radius:14px;padding:36px 36px 32px;">

        <p style="margin:0 0 8px;font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:#72a37a;">
          New discussion activity
        </p>
        <h1 style="margin:0 0 16px;font-size:22px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;">
          ${opts.commenterName} commented on an article you follow
        </h1>

        <!-- Article title -->
        <p style="margin:0 0 4px;font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:rgba(255,255,255,0.35);">Article</p>
        <p style="margin:0 0 20px;font-size:14px;color:#ffffff;line-height:1.5;font-style:italic;">${opts.alertTitle}</p>

        <!-- Comment snippet -->
        <table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:28px;">
          <tr>
            <td style="background:rgba(255,255,255,0.04);border-left:3px solid #72a37a;border-radius:0 8px 8px 0;padding:14px 16px;">
              <p style="margin:0;font-size:14px;color:#b0b0bc;line-height:1.6;">${snippet}</p>
              <p style="margin:8px 0 0;font-size:12px;color:rgba(255,255,255,0.35);">— ${opts.commenterName}</p>
            </td>
          </tr>
        </table>

        <!-- CTA -->
        <table cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
          <tr>
            <td style="background:#72a37a;border-radius:9px;">
              <a href="${portalUrl}" style="display:inline-block;padding:13px 28px;font-size:14px;font-weight:700;color:#ffffff;text-decoration:none;letter-spacing:-0.2px;">
                Read the discussion →
              </a>
            </td>
          </tr>
        </table>

        <p style="margin:0;font-size:12px;color:rgba(255,255,255,0.35);line-height:1.6;">
          You're receiving this because you have comment notifications enabled.
          You can turn these off in your profile settings on the CarcinoS portal.
        </p>

      </td></tr>

      <!-- Footer -->
      <tr><td style="padding-top:24px;font-size:11px;color:rgba(255,255,255,0.25);line-height:1.7;text-align:center;">
        <p style="margin:0;">CarcinoS LLC · Salient Oncology Intelligence</p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>`;
}

// ── Main handler ──────────────────────────────────────────────────────────────

Deno.serve(async (req: Request) => {
  try {
    // Supabase Database Webhooks send a POST with the record payload
    if (req.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const payload = await req.json();

    // Webhook payload shape: { type: "INSERT", table: "comments", record: {...} }
    if (payload.type !== "INSERT" || payload.table !== "comments") {
      return new Response("Ignored", { status: 200 });
    }

    const comment = payload.record as {
      alert_id: string;
      user_id: string;       // auth.users UUID of the commenter
      display_name: string;
      content: string;
    };

    if (!comment.alert_id || !comment.user_id) {
      return new Response("Missing fields", { status: 400 });
    }

    // Fetch alert title for the email
    const sb = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

    const { data: alertData, error: alertErr } = await sb
      .from("alerts")
      .select("title")
      .eq("id", comment.alert_id)
      .single();

    if (alertErr || !alertData) {
      console.error("Failed to fetch alert:", alertErr);
      return new Response("Alert not found", { status: 404 });
    }

    // Get notification recipients via the SQL function
    const { data: recipients, error: recipErr } = await sb.rpc(
      "get_comment_notification_recipients",
      {
        p_alert_id: comment.alert_id,
        p_commenter_auth_id: comment.user_id,
      }
    );

    if (recipErr) {
      console.error("Failed to fetch recipients:", recipErr);
      return new Response("Recipient lookup failed", { status: 500 });
    }

    if (!recipients || recipients.length === 0) {
      console.log("No recipients for this comment — nothing to send.");
      return new Response("No recipients", { status: 200 });
    }

    console.log(`Sending comment notification to ${recipients.length} recipient(s)...`);

    // Send one email per recipient
    const sends = recipients.map(
      async (r: { email: string; full_name: string }) => {
        const html = buildEmail({
          recipientName: r.full_name || "there",
          commenterName: comment.display_name || "A colleague",
          alertTitle: alertData.title,
          alertId: comment.alert_id,
          commentSnippet: comment.content,
        });

        const res = await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${RESEND_API_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            from: FROM_EMAIL,
            to: [r.email],
            subject: `New comment on CarcinoS: ${alertData.title.slice(0, 60)}`,
            html,
          }),
        });

        if (!res.ok) {
          const err = await res.text();
          console.error(`Failed to send to ${r.email}:`, err);
        } else {
          console.log(`Sent to ${r.email}`);
        }
      }
    );

    await Promise.all(sends);

    return new Response(
      JSON.stringify({ sent: recipients.length }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  } catch (err) {
    console.error("Unexpected error:", err);
    return new Response("Internal error", { status: 500 });
  }
});
