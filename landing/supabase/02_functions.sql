-- ============================================================================
-- CarcinoS — Functions and triggers (v1)
-- Implements the audit-trail guarantee from spec §10:
--   "Every state change to an alert lands in alert_audit_log with action,
--    actor, and a JSON diff of what changed."
--
-- Paste this file into Supabase Studio → SQL Editor → Run AFTER 01_schema.sql.
-- Safe to re-run.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Helper: compute a JSON diff of changed top-level columns between OLD and NEW
-- alert rows. Only includes keys whose values changed (deep equality on JSONB).
-- ----------------------------------------------------------------------------
create or replace function public.alerts_diff(old_row alerts, new_row alerts)
returns jsonb language plpgsql immutable as $$
declare
  diff jsonb := '{}'::jsonb;
begin
  -- Columns worth tracking for audit purposes. summary_json is captured as
  -- a whole-object diff since field-level diffing is verbose and a downstream
  -- reviewer can compute it from the audit log if needed.
  if old_row.tier              is distinct from new_row.tier              then diff := diff || jsonb_build_object('tier',              jsonb_build_object('from', old_row.tier, 'to', new_row.tier)); end if;
  if old_row.status            is distinct from new_row.status            then diff := diff || jsonb_build_object('status',            jsonb_build_object('from', old_row.status, 'to', new_row.status)); end if;
  if old_row.title             is distinct from new_row.title             then diff := diff || jsonb_build_object('title',             jsonb_build_object('from', old_row.title, 'to', new_row.title)); end if;
  if old_row.intent            is distinct from new_row.intent            then diff := diff || jsonb_build_object('intent',            jsonb_build_object('from', old_row.intent, 'to', new_row.intent)); end if;
  if old_row.primary_endpoint  is distinct from new_row.primary_endpoint  then diff := diff || jsonb_build_object('primary_endpoint', jsonb_build_object('from', old_row.primary_endpoint, 'to', new_row.primary_endpoint)); end if;
  if old_row.confidence_tag    is distinct from new_row.confidence_tag    then diff := diff || jsonb_build_object('confidence_tag',   jsonb_build_object('from', old_row.confidence_tag, 'to', new_row.confidence_tag)); end if;
  if old_row.has_conflict      is distinct from new_row.has_conflict      then diff := diff || jsonb_build_object('has_conflict',     jsonb_build_object('from', old_row.has_conflict, 'to', new_row.has_conflict)); end if;
  if old_row.notify            is distinct from new_row.notify            then diff := diff || jsonb_build_object('notify',           jsonb_build_object('from', old_row.notify, 'to', new_row.notify)); end if;
  if old_row.summary_json      is distinct from new_row.summary_json      then diff := diff || jsonb_build_object('summary_json',     jsonb_build_object('from', old_row.summary_json, 'to', new_row.summary_json)); end if;
  return diff;
end; $$;

-- ----------------------------------------------------------------------------
-- Helper: derive an audit action name from a status transition. Falls back to
-- 'edited' if status didn't change but other fields did.
-- ----------------------------------------------------------------------------
create or replace function public.alerts_audit_action(old_status alert_status, new_status alert_status)
returns text language sql immutable as $$
  select case
    when old_status is distinct from new_status then
      case new_status
        when 'EXTRACTED'     then 'extracted'
        when 'EDITOR_REVIEW' then 'queued_for_review'
        when 'APPROVED'      then 'approved'
        when 'REJECTED'      then 'rejected'
        when 'PUBLISHED'     then 'published'
        when 'CORRECTED'     then 'corrected'
        else                       'status_changed'
      end
    else 'edited'
  end;
$$;

-- ----------------------------------------------------------------------------
-- INSERT trigger: log the creation of an alert.
-- ----------------------------------------------------------------------------
create or replace function public.alerts_audit_insert()
returns trigger language plpgsql security definer as $$
begin
  insert into alert_audit_log (alert_id, actor_id, action, diff)
  values (
    new.id,
    nullif(auth.uid(), '00000000-0000-0000-0000-000000000000'::uuid),
    case new.status
      when 'EXTRACTED' then 'extracted'
      else 'created'
    end,
    jsonb_build_object(
      'status',  new.status,
      'tier',    new.tier,
      'title',   new.title
    )
  );
  return new;
end; $$;

drop trigger if exists alerts_audit_insert_trg on alerts;
create trigger alerts_audit_insert_trg
  after insert on alerts
  for each row execute function public.alerts_audit_insert();

-- ----------------------------------------------------------------------------
-- UPDATE trigger: only log when at least one tracked column actually changed.
-- This avoids audit-log spam from no-op updates (set updated_at, etc.).
-- ----------------------------------------------------------------------------
create or replace function public.alerts_audit_update()
returns trigger language plpgsql security definer as $$
declare
  diff jsonb;
begin
  diff := public.alerts_diff(old, new);
  if diff = '{}'::jsonb then
    return new;
  end if;

  insert into alert_audit_log (alert_id, actor_id, action, diff)
  values (
    new.id,
    coalesce(
      new.approved_by,    -- actor if this transition is an approval
      new.rejected_by,    -- or a rejection
      nullif(auth.uid(), '00000000-0000-0000-0000-000000000000'::uuid)
    ),
    public.alerts_audit_action(old.status, new.status),
    diff
  );
  return new;
end; $$;

drop trigger if exists alerts_audit_update_trg on alerts;
create trigger alerts_audit_update_trg
  after update on alerts
  for each row execute function public.alerts_audit_update();

-- ----------------------------------------------------------------------------
-- Correction trigger: every row in `corrections` is itself an audit event.
-- Mirrors the spec §10 requirement that corrections are first-class.
-- ----------------------------------------------------------------------------
create or replace function public.corrections_audit_insert()
returns trigger language plpgsql security definer as $$
begin
  insert into alert_audit_log (alert_id, actor_id, action, diff)
  values (
    new.alert_id,
    new.corrected_by,
    'corrected',
    jsonb_build_object('note', new.note, 'patched_fields', new.patched_fields)
  );
  return new;
end; $$;

drop trigger if exists corrections_audit_insert_trg on corrections;
create trigger corrections_audit_insert_trg
  after insert on corrections
  for each row execute function public.corrections_audit_insert();

-- ============================================================================
-- Sanity helper for the founder editor: latest audit events.
-- ============================================================================
create or replace view public.alert_audit_recent as
  select
    al.created_at,
    al.alert_id,
    a.title,
    a.tier,
    al.action,
    u.email as actor_email,
    al.diff
  from alert_audit_log al
  join alerts a on a.id = al.alert_id
  left join users u on u.id = al.actor_id
  order by al.created_at desc;

-- Editor can read the view (it composes RLS from the underlying tables).
grant select on public.alert_audit_recent to authenticated;

-- ============================================================================
-- DONE.
-- ============================================================================
