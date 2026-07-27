-- ============================================================================
-- CarcinoS — Migration 05: Push Token Storage
--
-- Adds push_token to users table so the mobile app can register its
-- Expo push token and the delivery pipeline can send push notifications.
--
-- Paste into Supabase Studio → SQL Editor → Run.
-- Safe to re-run.
-- ============================================================================

-- Add push_token column to users
alter table users
  add column if not exists push_token text;

-- Index for the delivery script — it queries push_token IS NOT NULL
create index if not exists users_push_token_idx
  on users (push_token)
  where push_token is not null;

-- ============================================================================
-- store_push_token(token)
-- Called by the mobile app on launch after requesting push permissions.
-- Updates the push_token for the currently signed-in user.
-- Also updates delivery to 'both' if it was previously 'email' and the
-- user has now registered a device — this keeps delivery in sync with
-- the user's actual capability without requiring a manual settings change.
-- ============================================================================
create or replace function public.store_push_token(p_token text)
returns void
security definer
language plpgsql as $$
begin
  update users
  set
    push_token = p_token,
    -- If user had email-only but now has a push token, upgrade to 'both'
    -- (only if delivery column exists and is set to email)
    delivery = case
      when delivery = 'email' then 'both'
      else delivery
    end
  where id = auth.uid();
end;
$$;

grant execute on function public.store_push_token(text) to authenticated;

-- ============================================================================
-- clear_push_token()
-- Called when the user signs out of the mobile app or revokes push
-- permissions. Removes the token so the delivery script doesn't attempt
-- to send to a stale/invalid token.
-- ============================================================================
create or replace function public.clear_push_token()
returns void
security definer
language plpgsql as $$
begin
  update users
  set push_token = null
  where id = auth.uid();
end;
$$;

grant execute on function public.clear_push_token() to authenticated;

-- ============================================================================
-- DONE.
-- After running:
--   - Mobile app calls store_push_token(token) on launch after auth
--   - Delivery script queries users where push_token IS NOT NULL
--     and delivery IN ('push', 'both') to send push notifications
-- ============================================================================
