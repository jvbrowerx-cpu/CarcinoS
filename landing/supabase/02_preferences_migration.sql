-- ============================================================================
-- CarcinoS — Migration v2: User Subscription Preferences
-- Adds oncology_scope (all / radiation_only) to users,
-- push_opt_in to subscriptions, and anon-safe RLS for signup.
--
-- Run in Supabase Studio → SQL Editor → Run.
-- Safe to re-run (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- ============================================================================

-- ── New enum: oncology_scope ─────────────────────────────────────────────────
do $$ begin
  create type oncology_scope as enum (
    'all',             -- all oncology alerts across selected disease sites
    'radiation_only'   -- only alerts with radiation oncology relevance
  );
exception when duplicate_object then null; end $$;

-- ── New enum: delivery_channel (user-level) ──────────────────────────────────
do $$ begin
  create type delivery_channel as enum (
    'email',           -- weekly email digest only
    'push',            -- push notifications only
    'both'             -- email digest + push notifications
  );
exception when duplicate_object then null; end $$;

-- ── Alter users: add preference columns ──────────────────────────────────────
alter table users
  add column if not exists oncology_scope   oncology_scope   not null default 'all',
  add column if not exists delivery         delivery_channel not null default 'email',
  add column if not exists specialty        text,            -- free-text: e.g. "Medical Oncology"
  add column if not exists verified         boolean not null default false;

-- ── Alter subscriptions: add push_opt_in ─────────────────────────────────────
-- email_opt_in already exists; push is new.
alter table subscriptions
  add column if not exists push_opt_in boolean not null default false;

-- ── Helper view: user preference summary ────────────────────────────────────
-- Flattens user prefs + their subscribed site codes into one row per user.
-- Useful for the delivery pipeline to query "who wants what".
create or replace view user_preference_summary as
select
  u.id                               as user_id,
  u.email,
  u.oncology_scope,
  u.delivery,
  u.specialty,
  u.verified,
  array_agg(ds.code order by ds.code) filter (
    where s.is_active = true
  )                                   as subscribed_sites,
  bool_or(s.email_opt_in)            as any_email_opt_in,
  bool_or(s.push_opt_in)             as any_push_opt_in,
  bool_or(s.notify_tier_a)           as notify_tier_a,
  bool_or(s.notify_tier_b)           as notify_tier_b
from users u
left join subscriptions s  on s.user_id = u.id and s.is_active = true
left join disease_sites  ds on ds.id = s.disease_site_id
group by u.id;

-- ── RLS: allow anon signup ───────────────────────────────────────────────────
-- The landing page signup form runs as the anon role (no auth token).
-- We allow anon INSERT to users + subscriptions for new signups only.
-- Anon cannot SELECT, UPDATE, or DELETE their own rows — those require auth.

drop policy if exists users_anon_insert on users;
create policy users_anon_insert on users
  for insert to anon
  with check (role = 'subscriber');  -- anon can only create subscriber rows

drop policy if exists subscriptions_anon_insert on subscriptions;
create policy subscriptions_anon_insert on subscriptions
  for insert to anon
  with check (true);   -- user_id FK enforces integrity; anon inserts only

-- Authenticated subscribers can read + update their own user row.
drop policy if exists users_owner_read on users;
create policy users_owner_read on users
  for select to authenticated
  using (id = auth.uid() or public.is_founder_editor());

drop policy if exists users_owner_update on users;
create policy users_owner_update on users
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid() and role = 'subscriber');  -- can't self-promote role

-- ── Function: upsert_subscriber ──────────────────────────────────────────────
-- Called by the landing page on form submit (via Supabase JS client).
-- Creates or updates a subscriber's preferences atomically.
-- Returns the user id.
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
  v_user_id  uuid;
  v_site_id  uuid;
  v_code     disease_site_code;
begin
  -- Upsert user
  insert into users (email, role, oncology_scope, delivery, specialty)
  values (p_email, 'subscriber', p_oncology_scope, p_delivery, p_specialty)
  on conflict (email) do update
    set oncology_scope = excluded.oncology_scope,
        delivery       = excluded.delivery,
        specialty      = excluded.specialty,
        -- keep verified flag unchanged on re-subscribe
        verified       = users.verified
  returning id into v_user_id;

  -- Deactivate all existing site subscriptions (full refresh)
  update subscriptions
  set is_active = false
  where user_id = v_user_id;

  -- Re-activate (or insert) each selected site
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
        p_delivery in ('email','both'),
        p_delivery in ('push','both')
      )
      on conflict (user_id, disease_site_id) do update
        set is_active    = true,
            email_opt_in = p_delivery in ('email','both'),
            push_opt_in  = p_delivery in ('push','both');
    end if;
  end loop;

  return v_user_id;
end;
$$;

-- Grant anon + authenticated roles permission to call the function
grant execute on function public.upsert_subscriber to anon, authenticated;

-- ============================================================================
-- DONE.
-- Next: 03_functions.sql — alert_audit_log trigger, alias-resolution helpers
-- ============================================================================
