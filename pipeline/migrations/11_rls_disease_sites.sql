-- Migration 11: Add authenticated read policy to disease_sites
--
-- disease_sites had only an anon SELECT policy (set in 01_schema.sql).
-- When the archive page added an auth gate, logged-in users gained the
-- `authenticated` role — which had no read policy on this table. As a result,
-- every disease_sites query returned empty silently, making disease_site_code
-- null for all alerts and breaking the site-specific filter in the archive.
--
-- Apply in the Supabase SQL Editor.

-- Allow logged-in users to read disease_sites (same as anon — it's public data).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE tablename = 'disease_sites'
      AND policyname = 'authenticated read disease_sites'
  ) THEN
    EXECUTE $policy$
      CREATE POLICY "authenticated read disease_sites"
        ON disease_sites FOR SELECT
        TO authenticated
        USING (true)
    $policy$;
  END IF;
END $$;

-- Verify both policies exist after running:
-- SELECT policyname, roles FROM pg_policies WHERE tablename = 'disease_sites';
