-- Deadline extension (owner-approved 2026-10-07, announced to every team).
-- The online phase ends 2026-10-07 21:59:59 UTC instead of 15:59:59 UTC. Evaluations,
-- final-version choice and everything else keyed to phases.ends_at follow automatically.
-- New: from the original deadline until the new one, each team may create at most 5 new
-- versions (revisions). Versions created before the original deadline do not count.
-- Rolling ends_at back to 15:59:59 empties the window and so also disables the cap.

create or replace function private.observer_extension_window()
returns table(opens_at timestamptz, closes_at timestamptz, max_versions integer)
language sql stable security definer set search_path = public, pg_temp as $$
  select timestamptz '2026-10-07 15:59:59+00', p.ends_at, 5
  from public.phases p where p.id = '049d6029-343d-4d16-80d5-94b56b350301'
$$;
revoke all on function private.observer_extension_window() from public;

create or replace function private.observer_extension_versions(p_team uuid)
returns jsonb
language sql stable security definer set search_path = public, pg_temp as $$
  select jsonb_build_object('active', now() >= w.opens_at and now() < w.closes_at,
    'opens_at', w.opens_at, 'closes_at', w.closes_at, 'limit', w.max_versions, 'used', u.used,
    'remaining', greatest(0, w.max_versions - u.used))
  from private.observer_extension_window() w
  cross join lateral (select count(*)::integer as used from public.observer_revisions r
    join public.observer_projects p on p.id = r.project_id
    where p.team_id = p_team and r.created_at >= w.opens_at) u
  where w.closes_at is not null and w.closes_at > w.opens_at
$$;
revoke all on function private.observer_extension_versions(uuid) from public;

-- The caller's team; null when there is no extension window.
create or replace function public.observer_extension_versions()
returns jsonb
language sql stable security definer set search_path = public, pg_temp as $$
  select private.observer_extension_versions(u.team_id) from public.profiles u
  where u.id = auth.uid() and u.team_id is not null
$$;
revoke all on function public.observer_extension_versions() from public, anon;
grant execute on function public.observer_extension_versions() to authenticated;

-- observer_create_project locks the team row before inserting, so the count is serialized.
create or replace function private.observer_revision_extension_cap()
returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare v_team uuid; v jsonb;
begin
  select team_id into v_team from public.observer_projects where id = new.project_id;
  v := private.observer_extension_versions(v_team);
  if v is not null and (v->>'active')::boolean and (v->>'remaining')::integer <= 0 then
    raise exception 'extension_version_limit';
  end if;
  return new;
end $$;
revoke all on function private.observer_revision_extension_cap() from public;

drop trigger if exists observer_revision_extension_cap on public.observer_revisions;
create trigger observer_revision_extension_cap before insert on public.observer_revisions
  for each row execute function private.observer_revision_extension_cap();

update public.phases set ends_at = timestamptz '2026-10-07 21:59:59+00'
  where id = '049d6029-343d-4d16-80d5-94b56b350301' and ends_at = timestamptz '2026-10-07 15:59:59+00';
