-- ============================================================================
-- CarcinoS — Migration 10: Specialty-based disease site filtering
--
-- Problem:
--   user_alert_feed filters disease sites via the subscriptions table only.
--   Setting user_preferences.specialty to 'breast_oncology', 'gi_oncology',
--   etc. had no effect on which disease sites appeared in the digest — the
--   specialty column was only read for the radiation_oncology relevance filter.
--   A user with specialty='breast_oncology' but subscriptions to all 10 sites
--   received all 10 sites' articles.
--
-- Fix:
--   1. Extend specialty_to_sites() to include 'pediatric' (added in migration 08).
--   2. Rebuild user_alert_feed so that specialty-specific values
--      (breast_oncology, gi_oncology, etc.) further restrict the disease sites
--      shown, in addition to the existing subscription filter.
--      - all_oncology / custom / radiation_oncology → subscriptions only
--      - any other specialty → intersect subscriptions with specialty_to_sites()
--
-- Safe to re-run: uses CREATE OR REPLACE throughout.
-- ============================================================================


-- ============================================================================
-- STEP 1: Update specialty_to_sites() to include pediatric
-- ============================================================================

-- Returns an ARRAY (not a set) so it can be used with = any() in WHERE clauses.
create or replace function public.specialty_to_sites(p_specialty specialty_group)
returns disease_site_code[]
language sql stable as $$
  select case p_specialty
    when 'all_oncology'
      then array['gynecologic','thoracic','head_neck','gu','breast','cns',
                 'gastrointestinal','cutaneous','hematologic','sarcoma',
                 'pediatric']::disease_site_code[]
    when 'radiation_oncology'
      then array['gynecologic','thoracic','head_neck','gu','breast','cns',
                 'gastrointestinal','cutaneous','hematologic','sarcoma',
                 'pediatric']::disease_site_code[]
    when 'medical_oncology'
      then array['gynecologic','thoracic','head_neck','gu','breast','cns',
                 'gastrointestinal','cutaneous','sarcoma',
                 'pediatric']::disease_site_code[]
    when 'hematology_oncology'
      then array['hematologic']::disease_site_code[]
    when 'gynecologic_oncology'
      then array['gynecologic']::disease_site_code[]
    when 'thoracic_oncology'
      then array['thoracic']::disease_site_code[]
    when 'gu_oncology'
      then array['gu']::disease_site_code[]
    when 'breast_oncology'
      then array['breast']::disease_site_code[]
    when 'gi_oncology'
      then array['gastrointestinal']::disease_site_code[]
    when 'cns_oncology'
      then array['cns']::disease_site_code[]
    when 'cutaneous_oncology'
      then array['cutaneous']::disease_site_code[]
    when 'sarcoma_oncology'
      then array['sarcoma']::disease_site_code[]
    else
      array[]::disease_site_code[]
  end;
$$;


-- ============================================================================
-- STEP 2: Rebuild user_alert_feed with specialty-based site filtering
-- ============================================================================

create or replace view user_alert_feed as
select
  u.id                                          as user_id,
  u.email,
  coalesce(up.specialty, 'all_oncology')::text  as oncology_scope,
  coalesce(up.min_tier,  'A')::text             as min_tier,
  coalesce(up.email_opt_in, false)              as email_opt_in,
  ds.code::text                                 as disease_site_code,
  ds.name                                       as disease_site_name,
  a.id                                          as alert_id,
  a.title,
  a.tier::text                                  as tier,
  a.published_at,
  a.radiation_oncology_relevance,
  a.summary_json
from users u
left join user_preferences up on up.user_id = u.id
-- Active site subscriptions
join subscriptions s
  on  s.user_id  = u.id
  and s.is_active = true
join disease_sites ds on ds.id = s.disease_site_id
-- Alerts for those sites
join alerts a
  on  a.disease_site_id = ds.id
  and a.status          = 'PUBLISHED'

  -- ── Tier filter ──────────────────────────────────────────────────────────
  -- min_tier A → Practice Impacting only
  -- min_tier B → A + Incremental
  -- min_tier C → all tiers
  and (
    (coalesce(up.min_tier, 'A')::text = 'A' and a.tier::text = 'A')
    or (coalesce(up.min_tier, 'A')::text = 'B' and a.tier::text in ('A','B'))
    or  coalesce(up.min_tier, 'A')::text = 'C'
  )

  -- ── Radiation oncology relevance filter ──────────────────────────────────
  -- Only applies when specialty = 'radiation_oncology'.
  -- All other specialties pass through here (disease site filter below handles them).
  and (
    coalesce(up.specialty, 'all_oncology')::text != 'radiation_oncology'
    or a.radiation_oncology_relevance in ('direct', 'indirect')
  )

  -- ── Specialty-based disease site filter ──────────────────────────────────
  -- all_oncology / custom → no additional restriction; subscriptions are the filter.
  -- radiation_oncology    → no additional restriction here (handled by relevance filter above).
  -- Any other specialty (breast_oncology, gi_oncology, etc.) → article's disease
  --   site must be in the specialty's mapped site list from specialty_to_sites().
  -- This means a breast_oncology user with subscriptions to all 10 sites will still
  -- only see breast articles, while a custom user controls their feed via subscriptions.
  and (
    coalesce(up.specialty, 'all_oncology')::specialty_group
      in ('all_oncology'::specialty_group,
          'custom'::specialty_group,
          'radiation_oncology'::specialty_group)
    or ds.code = any(
        public.specialty_to_sites(
          coalesce(up.specialty, 'all_oncology')::specialty_group
        )
      )
  );

alter view user_alert_feed owner to postgres;

-- ============================================================================
-- DONE.
-- After running:
--   - Users with specialty='breast_oncology' see only breast alerts.
--   - Users with specialty='all_oncology' or 'custom' see all subscribed sites.
--   - radiation_oncology still applies the relevance filter on top of all sites.
--   - pediatric is now included in all_oncology, radiation_oncology, and
--     medical_oncology specialty mappings.
-- ============================================================================
