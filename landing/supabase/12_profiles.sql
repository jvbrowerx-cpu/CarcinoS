-- ============================================================================
-- CarcinoS — Migration 12: User profiles table
--
-- Stores display name, credentials, and institution for authenticated users.
-- Referenced at comment post-time to derive the formatted author string.
--
-- Prerequisites: migrations 01–11 run, Supabase Auth enabled.
-- Safe to re-run: uses IF NOT EXISTS / OR REPLACE throughout.
-- ============================================================================


-- ============================================================================
-- STEP 1: Profiles table
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.profiles (
  user_id      uuid        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name    text        NOT NULL DEFAULT '',
  credentials  text        NOT NULL DEFAULT '',   -- 'MD', 'MD PhD', 'DO', etc.
  institution  text        NOT NULL DEFAULT '',
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_profiles_user_id ON public.profiles (user_id);


-- ============================================================================
-- STEP 2: Row Level Security
-- ============================================================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

-- Any authenticated user can read any profile (needed to display comment authors)
DROP POLICY IF EXISTS "profiles_select" ON public.profiles;
CREATE POLICY "profiles_select"
  ON public.profiles FOR SELECT
  TO authenticated
  USING (true);

-- Users can only insert their own profile
DROP POLICY IF EXISTS "profiles_insert" ON public.profiles;
CREATE POLICY "profiles_insert"
  ON public.profiles FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

-- Users can only update their own profile
DROP POLICY IF EXISTS "profiles_update" ON public.profiles;
CREATE POLICY "profiles_update"
  ON public.profiles FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id);


-- ============================================================================
-- DONE.
--
-- After running:
--   - Signup flow collects full_name, credentials, institution
--   - Profile is upserted on signup and stored in public.profiles
--   - Comments display formatted author: "Jane Smith, MD · Memorial Sloan Kettering"
--   - Users can update their profile in future (account settings, not yet built)
-- ============================================================================
