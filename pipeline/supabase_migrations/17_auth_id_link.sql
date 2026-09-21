-- Migration 17: Link public.users to auth.users via auth_id
--
-- Problem: public.users.id is a separate gen_random_uuid(), making it
-- impossible to write correct RLS policies using auth.uid().
--
-- Solution: Add auth_id column that stores the auth.users UUID for members
-- who have accounts. Email-only subscribers get auth_id = NULL (fine).
--
-- Run in Supabase Dashboard → SQL Editor.

-- ─── 1. Add auth_id column ─────────────────────────────────────────────────

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS auth_id uuid REFERENCES auth.users(id);

-- ─── 2. Backfill existing full members ─────────────────────────────────────
-- Matches on email (case-insensitive). Email-only subscribers are left NULL.

UPDATE public.users u
SET auth_id = au.id
FROM auth.users au
WHERE lower(au.email) = lower(u.email::text)
  AND u.auth_id IS NULL;

-- ─── 3. Index for RLS performance ──────────────────────────────────────────

CREATE INDEX IF NOT EXISTS users_auth_id_idx ON public.users (auth_id);

-- ─── 4. Auto-populate auth_id when a new auth account is created ───────────
-- Fires whenever someone completes signup — links their public.users row
-- (created earlier by upsert_subscriber) to their new auth account.

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.users
  SET auth_id = NEW.id
  WHERE lower(email) = lower(NEW.email::text)
    AND auth_id IS NULL;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();

-- ─── 5. Fix RLS on public.users ────────────────────────────────────────────
-- Old users_owner_read used id = auth.uid() which never matched because
-- public.users.id is a separate UUID. Now correctly uses auth_id.

DROP POLICY IF EXISTS users_owner_read ON public.users;
CREATE POLICY users_owner_read ON public.users
  FOR SELECT TO authenticated
  USING (auth_id = auth.uid() OR is_founder_editor());

DROP POLICY IF EXISTS users_owner_update ON public.users;
CREATE POLICY users_owner_update ON public.users
  FOR UPDATE TO authenticated
  USING (auth_id = auth.uid() OR is_founder_editor());

-- ─── 6. Add SELECT policy on subscriptions ─────────────────────────────────
-- Lets logged-in users read their own disease site subscriptions.
-- The profile modal needs this to load which sites are active.
-- upsert_subscriber (SECURITY DEFINER) already bypasses RLS for writes.

DROP POLICY IF EXISTS subscriptions_owner_read ON public.subscriptions;
CREATE POLICY subscriptions_owner_read ON public.subscriptions
  FOR SELECT TO authenticated
  USING (
    user_id = (SELECT id FROM public.users WHERE auth_id = auth.uid())
    OR is_founder_editor()
  );

-- ─── Verification ──────────────────────────────────────────────────────────
-- Run after migration to confirm backfill worked:
--
-- SELECT email, auth_id IS NOT NULL AS has_auth_link
-- FROM public.users
-- ORDER BY has_auth_link DESC, email;
