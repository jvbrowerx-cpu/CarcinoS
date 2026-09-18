-- Migration 18: Reliable signup triggers
--
-- Problem 1: profiles row not created on signup because the JS upsert
--   fails silently (RLS, session timing, or other client-side issue).
-- Problem 2: auth_id not set on public.users when auth is created before
--   the public.users row exists (current landing page signup order).
--
-- Solution: Move both critical operations to the database layer via triggers
--   so they happen reliably regardless of what the JS does.
--
-- Run in Supabase Dashboard → SQL Editor.

-- ─── 1. Auto-create profiles row on auth signup ────────────────────────────
-- Fires the moment a new auth.users row is inserted.
-- JS then updates name/credentials/institution on the existing row (simpler UPDATE).

CREATE OR REPLACE FUNCTION public.handle_new_auth_user_profile()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (user_id, updated_at)
  VALUES (NEW.id, now())
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created_profile ON auth.users;
CREATE TRIGGER on_auth_user_created_profile
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user_profile();

-- ─── 2. Auto-set auth_id when public.users row is inserted ────────────────
-- The landing page calls upsert_subscriber BEFORE auth.signUp(), so when
-- the public.users row is created, the auth account may already exist.
-- This trigger sets auth_id immediately on INSERT if auth account is found.

CREATE OR REPLACE FUNCTION public.handle_new_public_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_auth_id uuid;
BEGIN
  IF NEW.auth_id IS NULL THEN
    SELECT id INTO v_auth_id
    FROM auth.users
    WHERE lower(email) = lower(NEW.email::text)
    LIMIT 1;

    IF v_auth_id IS NOT NULL THEN
      UPDATE public.users SET auth_id = v_auth_id WHERE id = NEW.id;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_public_user_created ON public.users;
CREATE TRIGGER on_public_user_created
  AFTER INSERT ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_public_user();

-- ─── 3. Backfill any existing users missing auth_id ───────────────────────

UPDATE public.users u
SET auth_id = au.id
FROM auth.users au
WHERE lower(au.email) = lower(u.email::text)
  AND u.auth_id IS NULL;

-- ─── Verification ─────────────────────────────────────────────────────────
-- After running, confirm all auth users now have profiles:
--
-- SELECT au.email, p.user_id IS NOT NULL AS has_profile
-- FROM auth.users au
-- LEFT JOIN public.profiles p ON p.user_id = au.id
-- ORDER BY has_profile, au.email;
