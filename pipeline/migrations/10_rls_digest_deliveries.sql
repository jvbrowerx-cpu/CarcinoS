-- Migration 10: Enable RLS on digest_deliveries
--
-- digest_deliveries was created without Row-Level Security, making it
-- publicly readable/writable via the anon key. This migration locks it down:
-- only the service role (used by the pipeline server-side) can access it.
-- No anon or authenticated-user access is needed — this table is internal.
--
-- Apply in the Supabase SQL Editor.

ALTER TABLE digest_deliveries ENABLE ROW LEVEL SECURITY;

-- Service role has full access (pipeline delivery script uses service role key)
CREATE POLICY "service read digest_deliveries"
    ON digest_deliveries FOR SELECT
    TO service_role
    USING (true);

CREATE POLICY "service insert digest_deliveries"
    ON digest_deliveries FOR INSERT
    TO service_role
    WITH CHECK (true);

CREATE POLICY "service delete digest_deliveries"
    ON digest_deliveries FOR DELETE
    TO service_role
    USING (true);

-- No anon or authenticated access — this is internal pipeline data only.
