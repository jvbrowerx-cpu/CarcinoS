-- ============================================================================
-- CarcinoS — Migration 03: User Preferences & Specialty Groups
-- Adds user-level specialty/scope preference so users can choose to receive
-- updates for a specific specialty (e.g. Radiation Oncology, Hematology) or
-- all of oncology, in addition to per-site subscription toggles.
--
-- Paste into Supabase Studio → SQL Editor → Run.
-- Safe to re-run: uses IF NOT EXISTS / OR REPLACE throughout.
-- ============================================================================

-- ============================================================================
-- ENUM: specialty_group
-- Maps to clinical specialty or scope of practice.
-- 'custom' means the user has individually selected disease sites.
-- ============================================================================

do $$ begin
  create type specialty_group as enum (
    'all_oncology',           -- All disease sites (broadest)
    'radiation_oncology',     -- Rad onc treats all sites; same as all_oncology in practice
    'medical_oncology',       -- Solid tumor–focused med onc
    'hematology_oncology',    -- Hematologic malignancies only
    'gynecologic_oncology',   -- Gynecologic only
    'thoracic_oncology',      -- Thoracic only
    'gu_oncology',            -- GU only
    'breast_oncology',        -- Breast only
    'gi_oncology',            -- GI only
    'cns_oncology',           -- CNS/neuro-oncology only
    'cutaneous_oncology',     -- Cutaneous/melanoma only
    'sarcoma_oncology',       -- Sarcoma only
    'custom'                  -- User-defined via individual site toggles
  );
exception when duplicate_object then null; end $$;

-- ============================================================================
-- ENUM: alert_tier_min
-- Minimum tier the user wants to receive notifications for.
-- 'A' = Practice Impacting only (most selective)
-- 'B' = Practice Impacting + Incremental
-- 'C' = All tiers including Horizon
-- ============================================================================

do $$ begin
  create type alert_tier_min as enum ('A', 'B', 'C');
exception when duplicate_object then null; end $$;

-- ============================================================================
-- TABLE: user_preferences
-- One row per user; stores their specialty scope and notification settings.
-- Created alongside subscriptions (per-site toggles stay in that table).
-- ============================================================================

create table if not exists user_preferences (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null unique references users(id) on delete cascade,
  specialty        specialty_group not null default 'all_oncology',
  min_tier         alert_tier_min not null default 'A',  -- Practice Impacting only by default
  email_opt_in     boolean not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- Auto-update updated_at on any row change.
drop trigger if exists user_preferences_set_updated_at on user_preferences;
create trigger user_preferences_set_updated_at
  before update on user_preferences
  for each row execute function set_updated_at();

-- ============================================================================
-- ROW-LEVEL SECURITY
-- Users can only read/write their own preference row.
-- ============================================================================

alter table user_preferences enable row level security;

drop policy if exists user_preferences_owner_all on user_preferences;
create policy user_preferences_owner_all on user_preferences
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Founder editor can see all preferences (for support / admin purposes).
drop policy if exists user_preferences_editor_read on user_preferences;
create policy user_preferences_editor_read on user_preferences
  for select to authenticated
  using (public.is_founder_editor());

-- ============================================================================
-- HELPER: specialty_to_sites(specialty_group)
-- Returns the set of disease_site_code values that correspond to a given
-- specialty so the settings page (or a future server function) can auto-
-- populate subscriptions rows when a preset is selected.
--
-- Radiation Oncology gets all sites because rad onc treats all cancers.
-- Medical Oncology excludes hematologic by convention in this schema.
-- ============================================================================

create or replace function public.specialty_to_sites(p_specialty specialty_group)
returns setof disease_site_code
language sql stable as $$
  select unnest(
    case p_specialty
      when 'all_oncology'         then array['gynecologic','thoracic','head_neck','gu','breast','cns','gastrointestinal','cutaneous','hematologic','sarcoma']::disease_site_code[]
      when 'radiation_oncology'   then array['gynecologic','thoracic','head_neck','gu','breast','cns','gastrointestinal','cutaneous','hematologic','sarcoma']::disease_site_code[]
      when 'medical_oncology'     then array['gynecologic','thoracic','head_neck','gu','breast','cns','gastrointestinal','cutaneous','sarcoma']::disease_site_code[]
      when 'hematology_oncology'  then array['hematologic']::disease_site_code[]
      when 'gynecologic_oncology' then array['gynecologic']::disease_site_code[]
      when 'thoracic_oncology'    then array['thoracic']::disease_site_code[]
      when 'gu_oncology'          then array['gu']::disease_site_code[]
      when 'breast_oncology'      then array['breast']::disease_site_code[]
      when 'gi_oncology'          then array['gastrointestinal']::disease_site_code[]
      when 'cns_oncology'         then array['cns']::disease_site_code[]
      when 'cutaneous_oncology'   then array['cutaneous']::disease_site_code[]
      when 'sarcoma_oncology'     then array['sarcoma']::disease_site_code[]
      when 'custom'               then array[]::disease_site_code[]
      else                             array[]::disease_site_code[]
    end
  );
$$;

-- ============================================================================
-- DONE.
-- Next steps:
--   - Run this file in Supabase Studio SQL Editor
--   - The settings page reads/writes user_preferences and subscriptions
--     using the anon key + Supabase Auth (same pattern as the admin portal)
-- ============================================================================
