-- Migration 13: audience-based delivery routing
--
-- Adds `audience` column to the get_user_feed_for_digest() RPC output and
-- filters each user's feed so that:
--   radiation_oncology users  → only see alerts where audience @> '{radiation_oncology}'
--   all_oncology users        → only see alerts where audience @> '{broad_oncology}'
--
-- Because all existing cards defaulted to {broad_oncology, radiation_oncology}
-- (migration add_audience_column.sql), this change is fully backwards-compatible:
-- no subscriber loses cards they currently receive.
--
-- Run in Supabase SQL editor (postgres / service role).

CREATE OR REPLACE FUNCTION get_user_feed_for_digest(
    p_user_id uuid,
    p_since    timestamptz
)
RETURNS TABLE (
    alert_id                    uuid,
    title                       text,
    tier                        text,
    published_at                timestamptz,
    disease_site_code           text,
    disease_site_name           text,
    radiation_oncology_relevance text,
    oncology_scope              text,
    summary_json                jsonb,
    audience                    text[]
)
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT
        f.alert_id,
        f.title,
        f.tier,
        f.published_at,
        f.disease_site_code,
        f.disease_site_name,
        f.radiation_oncology_relevance,
        f.oncology_scope,
        f.summary_json,
        a.audience
    FROM user_alert_feed f
    JOIN alerts a ON a.id = f.alert_id
    WHERE f.user_id    = p_user_id
      AND f.published_at >= p_since
      -- Audience routing: match card audience against user's oncology scope
      AND (
          (f.oncology_scope = 'radiation_oncology' AND a.audience @> ARRAY['radiation_oncology'])
       OR (f.oncology_scope <> 'radiation_oncology' AND a.audience @> ARRAY['broad_oncology'])
      )
    ORDER BY
        CASE f.tier WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
        f.published_at DESC;
$$;

-- Verify: check the function now returns audience
-- SELECT proname, pronargs FROM pg_proc WHERE proname = 'get_user_feed_for_digest';
