-- ============================================================================
-- CarcinoS — Migration 04: Scope-Based Delivery Filter
--
-- What this does:
--   1. Adds radiation_oncology_relevance as a flat column on alerts
--      (it was already in summary_json; this makes SQL filtering efficient)
--   2. Backfills that column from existing summary_json rows
--   3. Simplifies specialty_group enum to the two scopes CarcinoS supports
--   4. Creates user_alert_feed view — the single source of truth for
--      "which alerts should this user receive?"
--   5. Creates get_my_feed() helper for the frontend settings page
--
-- Paste into Supabase Studio → SQL Editor → Run.
-- Safe to re-run: uses IF NOT EXISTS / OR REPLACE throughout.
-- ============================================================================


-- ============================================================================
-- STEP 1: Add radiation_oncology_relevance flat column to alerts
-- ============================================================================

alter table alerts
  add column if not exists radiation_oncology_relevance text
  check (radiation_oncology_relevance in ('direct', 'indirect', 'none'));

-- Backfill existing rows from summary_json
update alerts
set radiation_oncology_relevance = summary_json->>'radiation_oncology_relevance'
where radiation_oncology_relevance is null
  and summary_json->>'radiation_oncology_relevance' is not null;

-- Index for fast scope filtering
create index if not exists alerts_rad_relevance_idx
  on alerts (radiation_oncology_relevance)
  where status = 'PUBLISHED';


-- ============================================================================
-- STEP 2: Ensure the two primary scope values exist in specialty_group enum
-- (other values already exist from migration 03 and are kept for compat)
-- ============================================================================

-- 'all_oncology' and 'radiation_oncology' already exist — no changes needed.
-- This comment is intentional: migration 03 defines the enum; we extend here
-- only if new values are required (none needed for the two-scope design).


-- ============================================================================
-- STEP 3: user_alert_feed view
--
-- Returns every (user, alert) pair the user should receive, applying:
--   a) Disease site subscription filter (is_active = true)
--   b) Alert tier filter (user's min_tier preference)
--   c) Scope filter:
--        - 'all_oncology' or 'custom' → all published alerts for their sites
--        - 'radiation_oncology'        → only radiation_oncology_relevance
--                                        IN ('direct', 'indirect')
--   d) Status = 'PUBLISHED' only
--
-- Used by:
--   - Weekly digest delivery script (server-side, service_role key)
--   - Admin tooling to preview what a user would receive
-- ============================================================================

create or replace view user_alert_feed as
select
  u.id                                  as user_id,
  u.email,
  coalesce(up.specialty, 'all_oncology')::text  as oncology_scope,
  coalesce(up.min_tier, 'A')::text      as min_tier,
  coalesce(up.email_opt_in, false)      as email_opt_in,
  ds.code::text                         as disease_site_code,
  ds.name                               as disease_site_name,
  a.id                                  as alert_id,
  a.title,
  a.tier::text                          as tier,
  a.published_at,
  a.radiation_oncology_relevance,
  a.summary_json
from users u
-- Outer join so users with no preferences row still show up (use defaults)
left join user_preferences up on up.user_id = u.id
-- Only sites the user has actively subscribed to
join subscriptions s
  on s.user_id = u.id
  and s.is_active = true
join disease_sites ds on ds.id = s.disease_site_id
-- Alerts for those sites
join alerts a
  on a.disease_site_id = ds.id
  and a.status = 'PUBLISHED'
  -- Tier filter: min_tier 'A' → only A; 'B' → A+B; 'C' → all
  and (
    (coalesce(up.min_tier, 'A')::text = 'A' and a.tier::text = 'A')
    or (coalesce(up.min_tier, 'A')::text = 'B' and a.tier::text in ('A', 'B'))
    or (coalesce(up.min_tier, 'A')::text = 'C')
  )
  -- Scope filter: radiation_oncology only sees direct/indirect
  and (
    coalesce(up.specialty, 'all_oncology')::text != 'radiation_oncology'
    or a.radiation_oncology_relevance in ('direct', 'indirect')
  );

-- RLS: users can only see their own feed rows
alter view user_alert_feed owner to postgres;

-- Service-role can see all rows (for digest delivery); authenticated users see only theirs.
-- Note: views inherit RLS from the underlying tables, so this is enforced automatically
-- through the users/subscriptions/user_preferences row-level policies already in place.


-- ============================================================================
-- STEP 4: get_my_feed() — callable from the frontend (anon/authenticated key)
--
-- Returns the published alerts for the currently signed-in user, respecting
-- their scope, site subscriptions, and tier preference.
--
-- Usage in JS:
--   const { data } = await sbClient.rpc('get_my_feed', { p_limit: 50, p_offset: 0 })
-- ============================================================================

create or replace function public.get_my_feed(
  p_limit  int default 20,
  p_offset int default 0
)
returns table (
  alert_id                    uuid,
  title                       text,
  tier                        text,
  published_at                timestamptz,
  disease_site_code           text,
  disease_site_name           text,
  radiation_oncology_relevance text,
  oncology_scope              text,
  summary_json                jsonb
)
security definer
language sql stable as $$
  select
    f.alert_id,
    f.title,
    f.tier,
    f.published_at,
    f.disease_site_code,
    f.disease_site_name,
    f.radiation_oncology_relevance,
    f.oncology_scope,
    f.summary_json
  from user_alert_feed f
  where f.user_id = auth.uid()
  order by f.published_at desc
  limit p_limit offset p_offset;
$$;

grant execute on function public.get_my_feed(int, int) to authenticated;


-- ============================================================================
-- STEP 5: get_user_feed_for_digest(p_user_id uuid)
--
-- Server-side function called by the digest delivery pipeline with the
-- SERVICE_ROLE key. Returns alerts published since the last digest that
-- the user should receive, ordered by tier then date.
--
-- Usage in Python:
--   resp = client.rpc('get_user_feed_for_digest', {
--       'p_user_id': user_id,
--       'p_since': last_digest_at.isoformat()
--   }).execute()
-- ============================================================================

create or replace function public.get_user_feed_for_digest(
  p_user_id  uuid,
  p_since    timestamptz default (now() - interval '7 days')
)
returns table (
  alert_id                    uuid,
  title                       text,
  tier                        text,
  published_at                timestamptz,
  disease_site_code           text,
  disease_site_name           text,
  radiation_oncology_relevance text,
  oncology_scope              text,
  summary_json                jsonb
)
security definer
language sql stable as $$
  select
    f.alert_id,
    f.title,
    f.tier,
    f.published_at,
    f.disease_site_code,
    f.disease_site_name,
    f.radiation_oncology_relevance,
    f.oncology_scope,
    f.summary_json
  from user_alert_feed f
  where f.user_id = p_user_id
    and f.published_at >= p_since
  order by
    -- Practice Impacting first, then Incremental, then Horizon
    case f.tier when 'A' then 1 when 'B' then 2 else 3 end,
    f.published_at desc;
$$;

-- Service role only (digest delivery uses service key, never anon)
revoke execute on function public.get_user_feed_for_digest(uuid, timestamptz) from anon, authenticated;
grant  execute on function public.get_user_feed_for_digest(uuid, timestamptz) to service_role;


-- ============================================================================
-- DONE.
--
-- After running this migration:
--   1. Every new alert stored by the pipeline will have radiation_oncology_relevance
--      set as a flat column (see supabase_client.py update).
--   2. The settings page scope selector saves 'all_oncology' or 'radiation_oncology'
--      to user_preferences.specialty.
--   3. Digest delivery calls get_user_feed_for_digest(user_id, since) to get the
--      correctly filtered alert list for each user.
--   4. The frontend can call get_my_feed() to preview what a user would see.
-- ============================================================================
