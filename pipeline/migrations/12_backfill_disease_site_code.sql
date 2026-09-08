-- Migration 12: Backfill disease_site_code into alerts.summary_json
--
-- Eliminates the need for the archive page to join disease_sites or query it
-- separately. The code is denormalized directly into summary_json so the
-- frontend can read it with a plain alerts SELECT — no FK join, no RLS issues.
--
-- Safe to run multiple times (jsonb_build_object overwrites with same value).
-- Apply in the Supabase SQL Editor.

UPDATE alerts
SET summary_json = summary_json || jsonb_build_object('disease_site_code', ds.code)
FROM disease_sites ds
WHERE alerts.disease_site_id = ds.id;

-- Verify: every PUBLISHED alert should now have a non-null disease_site_code
-- SELECT COUNT(*) FROM alerts
-- WHERE status IN ('PUBLISHED','CORRECTED')
--   AND summary_json->>'disease_site_code' IS NULL;
-- Expected: 0
