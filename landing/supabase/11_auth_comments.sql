-- ============================================================================
-- CarcinoS — Migration 11: Comments table for authenticated users
--
-- What this does:
--   1. Creates the comments table linked to auth.users (Supabase Auth)
--   2. Enables Row Level Security:
--        - authenticated users can read, write, and delete their own comments
--        - anon users cannot read comment content
--   3. Creates get_comment_counts() — a SECURITY DEFINER function accessible
--      to anon so the logged-out "3 oncologists commented" teaser can work
--      without exposing comment content.
--
-- Prerequisites:
--   - Supabase Auth must be enabled in your project (Dashboard → Authentication)
--   - Run AFTER migrations 01–10
--
-- Safe to re-run: uses IF NOT EXISTS / OR REPLACE throughout.
-- ============================================================================


-- ============================================================================
-- STEP 1: Comments table
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.comments (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  alert_id     uuid        NOT NULL REFERENCES public.alerts(id)  ON DELETE CASCADE,
  user_id      uuid        NOT NULL REFERENCES auth.users(id)     ON DELETE CASCADE,
  display_name text        NOT NULL DEFAULT '',
  content      text        NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT comments_content_length CHECK (
    char_length(content) >= 1 AND char_length(content) <= 1000
  )
);

CREATE INDEX IF NOT EXISTS idx_comments_alert_id ON public.comments (alert_id);
CREATE INDEX IF NOT EXISTS idx_comments_user_id  ON public.comments (user_id);
CREATE INDEX IF NOT EXISTS idx_comments_created  ON public.comments (created_at DESC);


-- ============================================================================
-- STEP 2: Row Level Security
-- ============================================================================

ALTER TABLE public.comments ENABLE ROW LEVEL SECURITY;

-- Authenticated users can read all comments
DROP POLICY IF EXISTS "auth_read_comments" ON public.comments;
CREATE POLICY "auth_read_comments"
  ON public.comments FOR SELECT
  TO authenticated
  USING (true);

-- Authenticated users can post comments
DROP POLICY IF EXISTS "auth_insert_comments" ON public.comments;
CREATE POLICY "auth_insert_comments"
  ON public.comments FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

-- Users can delete their own comments
DROP POLICY IF EXISTS "auth_delete_own_comments" ON public.comments;
CREATE POLICY "auth_delete_own_comments"
  ON public.comments FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);

-- Anon: no direct access (counts come via the function below)


-- ============================================================================
-- STEP 3: get_comment_counts() — anon-accessible count function
--
-- Used by the logged-out this-week page to show "3 oncologists commented"
-- teasers without exposing comment content.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_comment_counts(p_alert_ids uuid[])
RETURNS TABLE (alert_id uuid, comment_count bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT   c.alert_id,
           COUNT(*)::bigint AS comment_count
  FROM     public.comments c
  WHERE    c.alert_id = ANY(p_alert_ids)
  GROUP BY c.alert_id;
$$;

GRANT EXECUTE ON FUNCTION public.get_comment_counts(uuid[]) TO anon, authenticated;


-- ============================================================================
-- DONE.
--
-- After running:
--   - Authenticated users can post and read comments on any alert
--   - Anon users can fetch comment counts via get_comment_counts()
--   - Comment content is never exposed to anon via direct table query
--   - Flip AUTH_ENABLED = true in this-week/index.html to activate the UI
-- ============================================================================
