-- Post-deadline submission window (owner decision 2026-10-07): the official deadline stays
-- 2026-10-07 15:59:59 UTC. Until online.ends_at (21:59:59 UTC) each team may still submit at most
-- 10 new versions, evaluate them and choose its final version (any confirmed version); then freeze.
create or replace function private.observer_extension_window()
returns table(opens_at timestamptz, closes_at timestamptz, max_versions integer)
language sql stable security definer set search_path = public, pg_temp as $$
  select timestamptz '2026-10-07 15:59:59+00', p.ends_at, 10
  from public.phases p where p.id = '049d6029-343d-4d16-80d5-94b56b350301'
$$;
revoke all on function private.observer_extension_window() from public;
