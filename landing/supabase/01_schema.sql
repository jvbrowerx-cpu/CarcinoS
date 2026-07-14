-- ============================================================================
-- CarcinoS — Initial Supabase Schema (v1)
-- Implements the data model in CarcinoS Developer Spec v1.0, Section 7,
-- plus the extraction schema in Section 5.1 (stored as JSONB) and the
-- editorial workflow states from Section 6.1.
--
-- Paste this entire file into Supabase Studio → SQL Editor → Run.
-- Safe to re-run: every object uses IF NOT EXISTS or CREATE OR REPLACE.
-- ============================================================================

-- ------- Extensions --------------------------------------------------------
create extension if not exists "pgcrypto";   -- gen_random_uuid()
create extension if not exists "citext";     -- case-insensitive emails

-- ============================================================================
-- ENUMS
-- ============================================================================

do $$ begin
  create type disease_site_code as enum (
    'gynecologic',
    'thoracic',
    'head_neck',
    'gu',
    'breast',
    'cns',
    'gastrointestinal',
    'cutaneous',
    'hematologic',
    'sarcoma'
  );
exception when duplicate_object then null; end $$;

-- Idempotent backfill: if the enum was created before 'sarcoma' was added,
-- this picks it up on a re-run without recreating the type.
alter type disease_site_code add value if not exists 'sarcoma';

do $$ begin
  create type disease_site_status as enum (
    'planned',                    -- defined but retrospective sweep not started
    'retrospective_in_progress',  -- landmark list being built
    'live',                       -- passed go-live gate; ingesting + publishing
    'paused'                      -- temporarily disabled
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type alert_tier as enum ('A', 'B', 'C');
exception when duplicate_object then null; end $$;

do $$ begin
  create type alert_status as enum (
    'INGESTED',        -- candidate discovered and stored
    'EXTRACTED',       -- AI has populated summary_json
    'EDITOR_REVIEW',   -- queued for founder review
    'APPROVED',        -- editor approved; eligible to publish
    'PUBLISHED',       -- visible in client feed
    'CORRECTED',       -- published but has a correction record
    'REJECTED'         -- editor rejected; retained for audit, never shown
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type source_type as enum (
    'journal',
    'abstract',       -- conference abstract
    'registry',       -- ClinicalTrials.gov, EudraCT, etc.
    'guideline',
    'press_release'   -- tracked only; never sole basis for numeric claims
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type notification_channel as enum ('in_app', 'email', 'push');
exception when duplicate_object then null; end $$;

do $$ begin
  create type user_role as enum (
    'founder_editor',   -- Phase 1 sole approver
    'subscriber',       -- clinicians receiving alerts
    'admin'             -- reserved for later
  );
exception when duplicate_object then null; end $$;

-- ============================================================================
-- TABLES
-- ============================================================================

-- ---- users ----------------------------------------------------------------
create table if not exists users (
  id          uuid primary key default gen_random_uuid(),
  email       citext unique not null,
  role        user_role not null default 'subscriber',
  created_at  timestamptz not null default now()
);

-- ---- disease_sites --------------------------------------------------------
create table if not exists disease_sites (
  id          uuid primary key default gen_random_uuid(),
  code        disease_site_code unique not null,
  name        text not null,
  status      disease_site_status not null default 'planned',
  created_at  timestamptz not null default now()
);

-- ---- subscriptions --------------------------------------------------------
create table if not exists subscriptions (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references users(id) on delete cascade,
  disease_site_id  uuid not null references disease_sites(id) on delete cascade,
  is_active        boolean not null default true,
  notify_tier_a    boolean not null default true,   -- default per spec 12.2
  notify_tier_b    boolean not null default true,
  email_opt_in     boolean not null default false,  -- default per spec 12.2
  created_at       timestamptz not null default now(),
  unique (user_id, disease_site_id)
);

-- ---- trials ---------------------------------------------------------------
-- Canonical trial record. Aliases live in trial_aliases for alias resolution
-- per spec 4.3 ("any candidate that matches >=1 id OR >=2 keywords OR fuzzy
-- match on aliases is linked to the same canonical trial").
create table if not exists trials (
  id               uuid primary key default gen_random_uuid(),
  canonical_name   text not null,
  phase            text,               -- '1','2','3','4','N/A'; free-form for flexibility
  disease_site_id  uuid not null references disease_sites(id),
  keywords         text[] not null default '{}',
  nct_id           text,               -- promoted from ids for indexing
  eudract_id       text,
  protocol_id      text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
create index if not exists trials_disease_site_idx on trials(disease_site_id);
create unique index if not exists trials_nct_idx on trials(nct_id) where nct_id is not null;
create index if not exists trials_keywords_gin on trials using gin(keywords);

-- ---- trial_aliases --------------------------------------------------------
create table if not exists trial_aliases (
  id         uuid primary key default gen_random_uuid(),
  trial_id   uuid not null references trials(id) on delete cascade,
  alias      text not null,
  created_at timestamptz not null default now(),
  unique (trial_id, alias)
);
create index if not exists trial_aliases_alias_lower_idx on trial_aliases(lower(alias));

-- ---- sources --------------------------------------------------------------
-- Each Source is a concrete retrieved artifact bound to a hash for audit.
-- text_hash binds an extraction to the exact bytes that were parsed (spec 10).
create table if not exists sources (
  id           uuid primary key default gen_random_uuid(),
  trial_id     uuid references trials(id) on delete set null, -- nullable; may link later
  type         source_type not null,
  title        text,
  venue        text,               -- journal or meeting name
  year         int,
  url          text,
  doi          text,
  text_hash    text not null,      -- sha256 of the captured raw_text
  raw_text     text,               -- captured text used for extraction (nullable if only metadata)
  ingested_at  timestamptz not null default now(),
  constraint sources_unique_url unique (type, text_hash)
);
create index if not exists sources_trial_idx on sources(trial_id);
create index if not exists sources_doi_idx on sources(lower(doi)) where doi is not null;

-- ---- alerts ---------------------------------------------------------------
-- The editorial unit. summary_json holds the full Section 5.1 extraction.
-- Promoted columns handle hot-path filtering (tier, status, disease_site_id).
create table if not exists alerts (
  id                         uuid primary key default gen_random_uuid(),
  trial_id                   uuid not null references trials(id),
  disease_site_id            uuid not null references disease_sites(id),
  primary_source_id          uuid references sources(id),
  tier                       alert_tier not null,
  status                     alert_status not null default 'INGESTED',
  title                      text not null,
  intent                     text,                         -- trial intent_statement
  primary_endpoint           text,                         -- 'NOT_REPORTED' sentinel allowed
  confidence_tag             text,                         -- see spec §2 card fields
  summary_json               jsonb not null default '{}'::jsonb, -- full §5.1 schema
  has_conflict               boolean not null default false,     -- multiple sources disagree
  primary_endpoint_present   boolean generated always as (
    primary_endpoint is not null
    and primary_endpoint <> ''
    and primary_endpoint <> 'NOT_REPORTED'
  ) stored,
  notify                     boolean not null default false,
  approved_by                uuid references users(id),
  approved_at                timestamptz,
  published_at               timestamptz,
  rejected_by                uuid references users(id),
  rejected_at                timestamptz,
  created_at                 timestamptz not null default now(),
  updated_at                 timestamptz not null default now(),

  -- Spec §8.2: Tier C never notifies.
  constraint tier_c_never_notifies check (
    not (tier = 'C' and notify = true)
  ),

  -- Spec §5.2: conflicts require editor resolution; do not notify.
  constraint conflict_blocks_notify check (
    not (has_conflict = true and notify = true)
  ),

  -- Published alerts must have an approver and an approval timestamp.
  constraint published_requires_approval check (
    status not in ('APPROVED','PUBLISHED','CORRECTED')
    or (approved_by is not null and approved_at is not null)
  ),

  -- summary_json must have the top-level shape from spec §5.1 once extracted.
  constraint summary_json_shape check (
    status = 'INGESTED'
    or (
      summary_json ? 'trial'
      and summary_json ? 'results'
      and summary_json ? 'classification'
      and summary_json ? 'sources'
    )
  )
);
create index if not exists alerts_disease_site_status_idx on alerts(disease_site_id, status);
create index if not exists alerts_tier_status_idx on alerts(tier, status);
create index if not exists alerts_trial_idx on alerts(trial_id);
create index if not exists alerts_published_at_idx on alerts(published_at desc) where status = 'PUBLISHED';

-- Auto-update updated_at on any row change.
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end; $$;

drop trigger if exists alerts_set_updated_at on alerts;
create trigger alerts_set_updated_at
  before update on alerts
  for each row execute function set_updated_at();

drop trigger if exists trials_set_updated_at on trials;
create trigger trials_set_updated_at
  before update on trials
  for each row execute function set_updated_at();

-- ---- corrections ----------------------------------------------------------
-- Never delete a published alert; correct with an audit record (spec §10).
create table if not exists corrections (
  id             uuid primary key default gen_random_uuid(),
  alert_id       uuid not null references alerts(id) on delete cascade,
  note           text not null,              -- one-sentence what-changed
  patched_fields jsonb not null default '{}'::jsonb, -- field-level diff
  corrected_at   timestamptz not null default now(),
  corrected_by   uuid not null references users(id)
);
create index if not exists corrections_alert_idx on corrections(alert_id);

-- ---- notifications --------------------------------------------------------
create table if not exists notifications (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references users(id) on delete cascade,
  alert_id   uuid not null references alerts(id) on delete cascade,
  channel    notification_channel not null,
  sent_at    timestamptz not null default now(),
  opened_at  timestamptz
);
create index if not exists notifications_user_sent_idx on notifications(user_id, sent_at desc);
create index if not exists notifications_alert_idx on notifications(alert_id);

-- ---- alert_audit_log ------------------------------------------------------
-- Full audit trail of every change to an alert (spec §10).
create table if not exists alert_audit_log (
  id         bigserial primary key,
  alert_id   uuid not null references alerts(id) on delete cascade,
  actor_id   uuid references users(id),
  action     text not null,         -- 'created','extracted','edited','approved','rejected','corrected','published'
  diff       jsonb not null default '{}'::jsonb, -- {field: {from, to}}
  created_at timestamptz not null default now()
);
create index if not exists alert_audit_log_alert_idx on alert_audit_log(alert_id, created_at desc);

-- ---- landmark_trials ------------------------------------------------------
-- Used for per-disease-site retrospective validation (spec §6.3).
-- Editor seeds this with 20-50 known landmark trials per site before go-live,
-- then the system flags each as `captured=true` when ingestion finds it.
create table if not exists landmark_trials (
  id                 uuid primary key default gen_random_uuid(),
  disease_site_id    uuid not null references disease_sites(id) on delete cascade,
  canonical_name     text not null,
  expected_nct_id    text,
  notes              text,
  captured           boolean not null default false,
  captured_alert_id  uuid references alerts(id),
  captured_at        timestamptz,
  created_at         timestamptz not null default now()
);
create index if not exists landmark_trials_site_idx on landmark_trials(disease_site_id);

-- ---- ingestion_runs -------------------------------------------------------
-- Observability for each ingestion pass (spec §10 metrics).
create table if not exists ingestion_runs (
  id                         uuid primary key default gen_random_uuid(),
  source_lane                text not null,   -- 'pubmed','clinicaltrials_gov','journal_rss','asco_abstracts', etc.
  disease_site_id            uuid references disease_sites(id), -- null if lane covers all sites
  started_at                 timestamptz not null default now(),
  completed_at               timestamptz,
  status                     text not null default 'running',   -- 'running','succeeded','failed'
  candidates_found           int not null default 0,
  candidates_passed_filter   int not null default 0,
  candidates_extracted       int not null default 0,
  alerts_created             int not null default 0,
  error_log                  text
);
create index if not exists ingestion_runs_started_idx on ingestion_runs(started_at desc);

-- ============================================================================
-- ROW-LEVEL SECURITY
-- ----------------------------------------------------------------------------
-- Phase 1 policy:
--   * anon role (public client) can SELECT only PUBLISHED alerts + a few
--     look-up tables (disease_sites that are 'live', corrections on published).
--   * authenticated role (logged-in clinicians later) gets the same + their
--     own subscriptions/notifications.
--   * service_role bypasses RLS and is used by the admin portal + ingestion
--     pipeline (via SUPABASE_SERVICE_ROLE_KEY on the server side only).
-- ============================================================================

alter table users              enable row level security;
alter table disease_sites      enable row level security;
alter table subscriptions      enable row level security;
alter table trials             enable row level security;
alter table trial_aliases      enable row level security;
alter table sources            enable row level security;
alter table alerts             enable row level security;
alter table corrections        enable row level security;
alter table notifications      enable row level security;
alter table alert_audit_log    enable row level security;
alter table landmark_trials    enable row level security;
alter table ingestion_runs     enable row level security;

-- Public: live disease sites are listable.
drop policy if exists disease_sites_public_read on disease_sites;
create policy disease_sites_public_read on disease_sites
  for select to anon, authenticated
  using (status = 'live');

-- Public: only PUBLISHED or CORRECTED alerts are readable.
drop policy if exists alerts_public_read on alerts;
create policy alerts_public_read on alerts
  for select to anon, authenticated
  using (status in ('PUBLISHED','CORRECTED'));

-- Public: corrections on publicly visible alerts are readable.
drop policy if exists corrections_public_read on corrections;
create policy corrections_public_read on corrections
  for select to anon, authenticated
  using (
    exists (
      select 1 from alerts a
      where a.id = corrections.alert_id
        and a.status in ('PUBLISHED','CORRECTED')
    )
  );

-- Authenticated users can manage only their own subscriptions/notifications.
-- (auth.uid() matches the users.id if you mirror auth.users into public.users.)
drop policy if exists subscriptions_owner_all on subscriptions;
create policy subscriptions_owner_all on subscriptions
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

drop policy if exists notifications_owner_read on notifications;
create policy notifications_owner_read on notifications
  for select to authenticated
  using (user_id = auth.uid());

-- NOTE: service_role bypasses RLS entirely. The ingestion pipeline runs
-- server-side and uses SUPABASE_SERVICE_ROLE_KEY to write alerts/sources.
-- The admin portal is a static HTML page that ships to the browser, so it
-- CANNOT hold the service role key safely. Instead, the admin signs in via
-- Supabase Auth using the anon key and the policies below grant
-- founder_editor users the access they need.

-- Helper: is the currently-authenticated user a founder_editor?
-- security definer so the policy can read public.users without recursing
-- into its own RLS.
create or replace function public.is_founder_editor() returns boolean
language sql security definer stable as $$
  select coalesce(
    (select role = 'founder_editor' from public.users where id = auth.uid()),
    false
  );
$$;

-- Founder editor can read/update all alerts (any status) so the admin
-- portal can surface the EXTRACTED queue and walk it through APPROVED →
-- PUBLISHED. The published_requires_approval CHECK constraint still applies.
drop policy if exists alerts_editor_all on alerts;
create policy alerts_editor_all on alerts
  for all to authenticated
  using (public.is_founder_editor())
  with check (public.is_founder_editor());

-- Editor needs to see all disease sites (not just 'live') for context.
drop policy if exists disease_sites_editor_read on disease_sites;
create policy disease_sites_editor_read on disease_sites
  for select to authenticated
  using (public.is_founder_editor() or status = 'live');

drop policy if exists sources_editor_read on sources;
create policy sources_editor_read on sources
  for select to authenticated
  using (public.is_founder_editor());

drop policy if exists trials_editor_read on trials;
create policy trials_editor_read on trials
  for select to authenticated
  using (public.is_founder_editor());

drop policy if exists corrections_editor_all on corrections;
create policy corrections_editor_all on corrections
  for all to authenticated
  using (public.is_founder_editor())
  with check (public.is_founder_editor());

drop policy if exists alert_audit_log_editor_read on alert_audit_log;
create policy alert_audit_log_editor_read on alert_audit_log
  for select to authenticated
  using (public.is_founder_editor());

-- ============================================================================
-- SEED DATA
-- ============================================================================

-- All 10 disease sites. All start 'planned' until their retrospective sweep
-- (§6.3) is complete — flip to 'live' one at a time.
--
-- NOTE on upgrades: if a previously-deployed database already had the
-- disease_site_code enum WITHOUT 'sarcoma', Postgres will not let the
-- newly-added enum value be used in the same transaction. In that case,
-- run this file twice (the first pass commits the new enum value; the
-- second pass seeds the row), or run `alter type disease_site_code add
-- value if not exists 'sarcoma';` once, then re-run this file.
insert into disease_sites (code, name, status) values
  ('gynecologic',      'Gynecologic',                      'planned'),
  ('thoracic',         'Thoracic',                         'planned'),
  ('head_neck',        'Head and Neck',                    'planned'),
  ('gu',               'Genitourinary (GU)',               'planned'),
  ('breast',           'Breast',                           'planned'),
  ('cns',              'Central Nervous System (CNS)',     'planned'),
  ('gastrointestinal', 'Gastrointestinal (GI)',            'planned'),
  ('cutaneous',        'Cutaneous',                        'planned'),
  ('hematologic',      'Hematologic',                      'planned'),
  ('sarcoma',          'Sarcoma',                          'planned')
on conflict (code) do nothing;

-- ============================================================================
-- DONE. Next migration files (planned):
--   02_functions.sql  — alert_audit_log trigger, alias-resolution helpers
--   03_seed_sources.sql — seed the journal/meeting/registry source whitelist
--   04_landmark_seed_gynecologic.sql — first disease-site landmark list
-- ============================================================================
