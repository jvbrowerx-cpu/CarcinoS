-- Migration 16: Comment notification preference + recipient function
--
-- 1. Adds comment_notifications boolean to profiles (default true — opt-out model)
-- 2. Creates get_comment_notification_recipients() function that returns the
--    emails of users who should be notified when a new comment is posted on
--    a given alert, excluding the commenter themselves.
--
-- Apply in the Supabase SQL Editor.

-- ── 1. Add preference column to profiles ──────────────────────────────────────

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS comment_notifications boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN profiles.comment_notifications IS
  'If true, email user when a new comment is posted on an article in their subscribed disease sites.';

-- ── 2. Recipient function ─────────────────────────────────────────────────────
--
-- Returns a table of (email, full_name) for every user who should receive a
-- comment notification for a given alert, excluding the user who posted it.
--
-- Logic:
--   a) Look up the alert's disease_site_code from summary_json
--   b) Find all public.users who are subscribed to that disease site
--      via the user_sites junction table
--   c) Cross-reference to auth.users (by email) to get the auth UUID
--   d) Join to profiles to check comment_notifications = true
--   e) Exclude the commenter (p_commenter_auth_id)
--
-- NOTE: user_sites uses public.users.id (NOT auth.users.id). The join to
-- auth.users is done by matching emails across the two tables.

CREATE OR REPLACE FUNCTION public.get_comment_notification_recipients(
  p_alert_id           uuid,
  p_commenter_auth_id  uuid
)
RETURNS TABLE (email text, full_name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  -- Get the disease_site_code for this alert
  WITH alert_site AS (
    SELECT summary_json->>'disease_site_code' AS site_code
    FROM   alerts
    WHERE  id = p_alert_id
  ),
  -- Find public.users subscribed to that disease site
  subscribed_public_users AS (
    SELECT u.id AS pub_user_id, u.email
    FROM   users u
    JOIN   user_sites us ON us.user_id = u.id
    JOIN   alert_site  a ON us.site_code = a.site_code
    WHERE  u.verified = true
  ),
  -- Cross-reference to auth.users to get auth UUID + check profiles
  eligible AS (
    SELECT
      spu.email,
      p.full_name
    FROM   subscribed_public_users spu
    JOIN   auth.users              au ON lower(au.email) = lower(spu.email)
    JOIN   profiles                p  ON p.user_id = au.id
    WHERE  p.comment_notifications = true
      AND  au.id <> p_commenter_auth_id   -- exclude the commenter
  )
  SELECT email, full_name FROM eligible;
$$;

-- Allow the service role to call this function (Edge Function uses service role key)
GRANT EXECUTE ON FUNCTION public.get_comment_notification_recipients(uuid, uuid)
  TO service_role;

-- ── Verify after running ──────────────────────────────────────────────────────
-- SELECT column_name, data_type, column_default
-- FROM   information_schema.columns
-- WHERE  table_name = 'profiles' AND column_name = 'comment_notifications';
--
-- SELECT proname FROM pg_proc WHERE proname = 'get_comment_notification_recipients';
