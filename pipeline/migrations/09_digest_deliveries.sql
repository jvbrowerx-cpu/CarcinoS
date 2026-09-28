-- Migration 09: Digest delivery tracking
--
-- Tracks which alert was sent to which user in each digest run, so the
-- delivery script can deduplicate across weeks and never send the same
-- article twice to the same subscriber.
--
-- Run in Supabase SQL Editor (safe to run multiple times — all objects use
-- IF NOT EXISTS).

-- ---- digest_deliveries ------------------------------------------------------
-- One row per (user, alert) pair.  The unique constraint is the guard that
-- prevents a duplicate send: if a row exists, skip the alert.
CREATE TABLE IF NOT EXISTS digest_deliveries (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  alert_id      uuid        NOT NULL REFERENCES alerts(id)  ON DELETE CASCADE,
  delivered_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, alert_id)
);

-- Index for the common query: "what has user X already received?"
CREATE INDEX IF NOT EXISTS idx_digest_deliveries_user
  ON digest_deliveries (user_id);

-- Index for the reverse lookup: "who has received alert Y?"
CREATE INDEX IF NOT EXISTS idx_digest_deliveries_alert
  ON digest_deliveries (alert_id);
