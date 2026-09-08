# Comment Notification Setup Guide

Follow these steps once to activate instant comment notifications.

---

## Step 1 — Run the SQL migration

In **Supabase Dashboard → SQL Editor**, paste and run the contents of:

```
supabase_migrations/16_comment_notifications.sql
```

This adds the `comment_notifications` column to `profiles` and creates the
`get_comment_notification_recipients()` function.

---

## Step 2 — Deploy the Edge Function

Install the Supabase CLI if you haven't already:
```bash
npm install -g supabase
```

Login and link your project:
```bash
supabase login
supabase link --project-ref <your-project-ref>
```

Deploy the function:
```bash
supabase functions deploy notify-comment
```

---

## Step 3 — Set Edge Function secrets

In **Supabase Dashboard → Edge Functions → notify-comment → Secrets**, add:

| Key | Value |
|-----|-------|
| `RESEND_API_KEY` | Your Resend API key |
| `CARCINOS_FROM_EMAIL` | `CarcinoS <digest@carcino-s.com>` |

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically.

---

## Step 4 — Create the Database Webhook

In **Supabase Dashboard → Database → Webhooks → Create a new hook**:

| Field | Value |
|-------|-------|
| Name | `on_comment_insert` |
| Table | `comments` |
| Events | `INSERT` |
| Type | `HTTP Request` |
| Method | `POST` |
| URL | `https://<your-project-ref>.supabase.co/functions/v1/notify-comment` |
| Headers | `Authorization: Bearer <your-service-role-key>` |

Save the webhook. From this point on, every new comment triggers an
instant email to all eligible subscribers.

---

## How it works

1. User posts a comment → database INSERT fires
2. Webhook calls the `notify-comment` Edge Function
3. Function calls `get_comment_notification_recipients(alert_id, commenter_id)`
4. Recipients = users subscribed to the article's disease site who have
   `comment_notifications = true` in their profile, excluding the commenter
5. One email per recipient sent via Resend

## User preferences

- **New signups**: checkbox on the landing page profile step (default: on)
- **Existing users**: ⚙ settings button in the this-week nav (visible when logged in)
