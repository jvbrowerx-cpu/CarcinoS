-- ============================================================================
-- CarcinoS — Migration 07: Fix scope preference in upsert_subscriber
--
-- Problem:
--   upsert_subscriber (migration 02) writes oncology scope to users.oncology_scope
--   (type: oncology_scope enum — 'all' | 'radiation_only').
--   But user_alert_feed (migration 04) reads scope from user_preferences.specialty
--   (type: specialty_group enum — 'all_oncology' | 'radiation_oncology' | ...).
--   upsert_subscriber never wrote to user_preferences, so scope filtering was
--   silently ignored — radiation-only users received all-oncology digests.
--
-- Fix:
--   Replace upsert_subscriber with a version that also upserts user_preferences,
--   mapping 'all' → 'all_oncology' and 'radiation_only' → 'radiation_oncology'.
--
-- Paste into Supabase Studio → SQL Editor → Run.
-- Safe to re-run: uses CREATE OR REPLACE.
-- ============================================================================

create or replace function public.upsert_subscriber(
  p_email           citext,
  p_oncology_scope  oncology_scope      default 'all',
  p_delivery        delivery_channel    default 'email',
  p_specialty       text                default null,
  p_site_codes      disease_site_code[] default '{}'
) returns uuid
language plpgsql security definer
as $$
declare
  v_user_id      uuid;
  v_site_id      uuid;
  v_code         disease_site_code;
  v_specialty_g  specialty_group;
begin
  -- Map oncology_scope enum → specialty_group for user_alert_feed
  v_specialty_g := case p_oncology_scope
    when 'radiation_only' then 'radiation_oncology'::specialty_group
    else                       'all_oncology'::specialty_group
  end;

  -- Upsert user row
  insert into users (email, role, oncology_scope, delivery, specialty)
  values (p_email, 'subscriber', p_oncology_scope, p_delivery, p_specialty)
  on conflict (email) do update
    set oncology_scope = excluded.oncology_scope,
        delivery       = excluded.delivery,
        specialty      = excluded.specialty,
        verified       = users.verified   -- keep verified flag on re-subscribe
  returning id into v_user_id;

  -- Upsert user_preferences so user_alert_feed picks up the correct scope
  insert into user_preferences (user_id, specialty, min_tier, email_opt_in)
  values (
    v_user_id,
    v_specialty_g,
    'A',                                        -- default: Practice Impacting only
    p_delivery in ('email', 'both')
  )
  on conflict (user_id) do update
    set specialty     = excluded.specialty,
        email_opt_in  = excluded.email_opt_in;

  -- Deactivate all existing site subscriptions (full refresh)
  update subscriptions
  set is_active = false
  where user_id = v_user_id;

  -- Re-activate (or insert) each selected disease site
  foreach v_code in array p_site_codes loop
    select id into v_site_id
    from disease_sites
    where code = v_code;

    if v_site_id is not null then
      insert into subscriptions (
        user_id, disease_site_id,
        is_active, notify_tier_a, notify_tier_b,
        email_opt_in, push_opt_in
      )
      values (
        v_user_id, v_site_id,
        true, true, true,
        p_delivery in ('email', 'both'),
        p_delivery in ('push',  'both')
      )
      on conflict (user_id, disease_site_id) do update
        set is_active    = true,
            email_opt_in = p_delivery in ('email', 'both'),
            push_opt_in  = p_delivery in ('push',  'both');
    end if;
  end loop;

  return v_user_id;
end;
$$;

-- Permissions unchanged — anon can call this for signup, authenticated for updates
grant execute on function public.upsert_subscriber to anon, authenticated;

-- ============================================================================
-- Backfill: fix existing subscribers whose user_preferences row is missing
-- or has the wrong specialty because the old function never wrote it.
-- ============================================================================

insert into user_preferences (user_id, specialty, min_tier, email_opt_in)
select
  u.id,
  case u.oncology_scope
    when 'radiation_only' then 'radiation_oncology'::specialty_group
    else                       'all_oncology'::specialty_group
  end,
  'A'::alert_tier_min,
  u.delivery in ('email', 'both')
from users u
where u.role = 'subscriber'
on conflict (user_id) do update
  set specialty    = excluded.specialty,
      email_opt_in = excluded.email_opt_in;

-- ============================================================================
-- DONE.
-- After running:
--   - New signups with 'radiation_only' scope will correctly receive only
--     radiation-relevant alerts (radiation_oncology_relevance IN ('direct','indirect'))
--   - Existing subscribers are backfilled so their scope is also corrected
-- ============================================================================
