-- ============================================================================
-- CarcinoS — Migration 06: Manual article entry support
--
-- Enables the editor to manually add articles from the admin portal that
-- CarcinoS didn't surface during automated ingestion.
--
-- Changes:
--   1. Makes alerts.trial_id nullable (manual entries have no NCT/trial row)
--   2. Adds alerts.is_manually_added flag
--   3. Grants the founder_editor role INSERT on alerts (anon key + auth)
--
-- Run in Supabase Studio → SQL Editor → Run.
-- ============================================================================

-- 1. Make trial_id nullable so manual entries can be inserted without a trial row.
--    Pipeline-ingested alerts always have a trial_id from upsert_source_and_trial().
ALTER TABLE alerts ALTER COLUMN trial_id DROP NOT NULL;

-- 2. Track which alerts were manually added by the editor vs. pipeline-ingested.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS is_manually_added BOOLEAN NOT NULL DEFAULT FALSE;

-- 3. Allow the founder_editor to INSERT new alerts (previously only SELECT/UPDATE
--    were exercised via the anon key + auth flow; the pipeline uses service_role).
--    The existing alerts_editor_all policy already covers FOR ALL, which includes
--    INSERT, so this is a no-op if you already ran 01_schema.sql as-is.
--    Re-creating it explicitly here for clarity:
DROP POLICY IF EXISTS alerts_editor_all ON alerts;
CREATE POLICY alerts_editor_all ON alerts
  FOR ALL TO authenticated
  USING (public.is_founder_editor())
  WITH CHECK (public.is_founder_editor());

-- Done. Manual articles inserted from the admin portal will have:
--   trial_id          = NULL
--   is_manually_added = TRUE
--   status            = 'APPROVED'
--   summary_json      = { trial, results, classification, sources, is_manually_added: true, … }
