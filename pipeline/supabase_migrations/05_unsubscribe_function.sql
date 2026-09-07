-- CarcinoS — Unsubscribe function
-- Run once in Supabase Studio → SQL Editor.
--
-- Creates a security-definer function that allows the anon role to mark a
-- user as unsubscribed (sets verified = false) given only their user UUID.
-- The UUID is embedded in every email footer and is not publicly guessable.

CREATE OR REPLACE FUNCTION public.unsubscribe_user(p_user_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE users
  SET verified = false
  WHERE id = p_user_id;
$$;

-- Allow the public (anon) role to call this function.
GRANT EXECUTE ON FUNCTION public.unsubscribe_user(uuid) TO anon;
