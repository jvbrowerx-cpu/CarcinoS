-- ============================================================================
-- CarcinoS — Migration 13: Auth user triggers
--
-- Two triggers fire after a new user is created in auth.users:
--
--   1. on_auth_user_created → handle_new_auth_user
--      Links the new auth account back to public.users by setting auth_id.
--
--   2. on_auth_user_created_profile → handle_new_auth_user_profile
--      Ensures a public.users row exists (fallback) and creates the profiles row.
--      Uses NEW.id (auth UUID) for profiles.user_id, which has a FK to auth.users(id).
--
-- Safe to re-run: uses CREATE OR REPLACE and IF NOT EXISTS.
-- ============================================================================


-- ============================================================================
-- FUNCTION 1: Link auth user back to public.users
-- ============================================================================

CREATE OR REPLACE FUNCTION public.handle_new_auth_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
  UPDATE public.users
  SET auth_id = NEW.id
  WHERE lower(email) = lower(NEW.email::text)
    AND auth_id IS NULL;
  RETURN NEW;
END;
$function$;

-- ============================================================================
-- FUNCTION 2: Ensure public.users and profiles rows exist
-- ============================================================================

CREATE OR REPLACE FUNCTION public.handle_new_auth_user_profile()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
BEGIN
  -- Ensure public.users row exists (fallback if signup bypassed upsert_subscriber)
  INSERT INTO public.users (email, delivery, verified)
  VALUES (NEW.email, 'email', false)
  ON CONFLICT (email) DO NOTHING;

  -- Create profiles row using the auth UUID (profiles.user_id FK → auth.users(id))
  INSERT INTO public.profiles (user_id, updated_at)
  VALUES (NEW.id, now())
  ON CONFLICT (user_id) DO NOTHING;

  RETURN NEW;
END;
$function$;

-- ============================================================================
-- TRIGGERS
-- ============================================================================

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user();

DROP TRIGGER IF EXISTS on_auth_user_created_profile ON auth.users;
CREATE TRIGGER on_auth_user_created_profile
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_auth_user_profile();

-- ============================================================================
-- DONE.
-- After running:
--   - New auth signups automatically set public.users.auth_id
--   - New auth signups automatically create a public.profiles row
--   - The save_profile RPC then fills in full_name, credentials, institution
-- ============================================================================
