-- Migration 07: pipeline_runs
--
-- Stores one row per weekly pipeline run containing the full attrition funnel
-- and per-journal coverage breakdown. Used by:
--   • Admin portal coverage panel (shows what the pipeline saw vs. kept)
--   • Subscriber email footer ("X papers scanned · Y selected this week")
--
-- Apply in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date    date        NOT NULL,           -- YYYY-MM-DD of the pipeline window end
    stats_json  jsonb       NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One row per run_date is the normal case; unique constraint prevents duplicates
-- from retries. On conflict, replace stats_json with the latest run.
CREATE UNIQUE INDEX IF NOT EXISTS pipeline_runs_run_date_idx ON pipeline_runs (run_date);

-- RLS: service role can write; anon can read (admin portal uses anon key)
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon read pipeline_runs"
    ON pipeline_runs FOR SELECT
    TO anon
    USING (true);

CREATE POLICY "service write pipeline_runs"
    ON pipeline_runs FOR INSERT
    TO service_role
    WITH CHECK (true);

CREATE POLICY "service update pipeline_runs"
    ON pipeline_runs FOR UPDATE
    TO service_role
    USING (true);

-- stats_json structure (written by run.py):
-- {
--   "papers_fetched":   312,        -- raw retrieval across all sites
--   "after_dedupe":     287,
--   "after_pubtype":    241,
--   "signal_kept":       47,        -- passed Gate 2 qualifying signal
--   "pass2_runs":        52,        -- total Pass 2 LLM calls (incl. QS_NONE promoted)
--   "papers_published":  18,        -- alerts surviving all caps (Tier A/B/C)
--   "by_tier": {"A": 4, "B": 9, "C": 5, "NOISE": 34},
--   "drop_reasons": {
--     "no_qualifying_signal": 198,
--     "gate1_hard_excluded":    6,
--     "pass2_noise":           34,
--     "quarantined":            8,
--     "trial_dedup_dropped":    2,
--     "cap_dropped":            0
--   },
--   "journals_fetched": {"Journal of Clinical Oncology": 34, ...},   -- top 30
--   "journals_kept":    {"Journal of Clinical Oncology":  6, ...},
--   "total_cost_usd": 1.2345
-- }
