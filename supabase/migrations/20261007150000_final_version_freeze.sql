-- 选定冻结 / Freeze selection: the team captain may lock the team's explicitly chosen final version
-- early, before the online phase ends. Afterwards observer_set_final_version refuses changes for that
-- team (final_version_frozen). Evaluations and new versions are unaffected.
-- Organizer undo (one team):
--   update private.observer_final_versions set frozen_at=null, frozen_by=null where team_id='<team>' and phase_id='<phase>';
alter table private.observer_final_versions
  add column if not exists frozen_at timestamptz,
  add column if not exists frozen_by uuid references public.profiles(id) on delete set null;

-- Same state as before, plus frozen_at/frozen_by of the explicit choice.
create or replace function private.observer_final_version_state(p_team uuid, p_phase uuid)
returns jsonb language sql stable security definer set search_path = public, pg_temp as $$
  with ph as (select p.id,p.ends_at from public.phases p where p.id=p_phase),
  chosen as (select f.revision_id,f.chosen_by,f.chosen_at,f.frozen_at,f.frozen_by from private.observer_final_versions f
    join public.observer_revisions r on r.id=f.revision_id join public.observer_projects j on j.id=r.project_id
    where f.team_id=p_team and f.phase_id=p_phase and j.team_id=p_team and r.status='approved' and r.archived_at is null),
  best as (select b.id,b.revision_id,b.score from public.observer_batches b
    where b.team_id=p_team and b.phase_id=p_phase and b.purpose='formal' and b.status='scored'
      and b.revision_id is not null and b.score is not null
    order by b.score desc,b.created_at,b.id limit 1)
  select jsonb_build_object('phase_id',ph.id,'deadline',ph.ends_at,
    'locked',ph.ends_at is not null and now()>=ph.ends_at,
    'revision_id',coalesce(c.revision_id,b.revision_id),
    'source',case when c.revision_id is not null then 'chosen' when b.revision_id is not null then 'best' end,
    'chosen_revision_id',c.revision_id,'chosen_by',c.chosen_by,'chosen_at',c.chosen_at,
    'best_batch_id',b.id,'best_revision_id',b.revision_id,'best_score',b.score,
    'frozen_at',c.frozen_at,'frozen_by',c.frozen_by)
  from ph left join chosen c on true left join best b on true
$$;

-- The caller's own view adds whether they are the captain and the team name (typed to confirm a freeze).
create or replace function public.observer_final_versions()
returns jsonb language sql stable security definer set search_path = public, pg_temp as $$
  select coalesce(jsonb_agg(private.observer_final_version_state(u.team_id,p.id)
      ||jsonb_build_object('is_captain',t.leader_id=u.id,'team_name',t.name) order by p.sort_order,p.id),'[]'::jsonb)
  from public.profiles u join public.teams t on t.id=u.team_id cross join public.phases p
  where u.id=auth.uid() and not u.is_banned and u.team_id is not null
    and private.observer_final_phase(p.id) and public.observer_phase_visible(p.id)
$$;

create or replace function public.observer_set_final_version(p_phase uuid, p_revision uuid default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_team uuid; v_phase public.phases; v_revision public.observer_revisions;
begin
  perform private.assert_not_banned();
  select team_id into v_team from public.profiles where id=auth.uid();
  if v_team is null then raise exception 'team_required'; end if;
  perform 1 from public.teams where id=v_team for update;
  select * into v_phase from public.phases where id=p_phase;
  if not found or not private.observer_final_phase(p_phase) or not public.observer_phase_visible(p_phase) then
    raise exception 'final_phase_invalid'; end if;
  if v_phase.ends_at is not null and now()>=v_phase.ends_at then raise exception 'final_version_locked'; end if;
  if exists(select 1 from private.observer_final_versions where team_id=v_team and phase_id=p_phase and frozen_at is not null) then
    raise exception 'final_version_frozen'; end if;
  if p_revision is null then
    delete from private.observer_final_versions where team_id=v_team and phase_id=p_phase;
  else
    select r.* into v_revision from public.observer_revisions r join public.observer_projects j on j.id=r.project_id
      where r.id=p_revision and j.team_id=v_team;
    if not found then raise exception 'revision_not_found'; end if;
    if v_revision.archived_at is not null then raise exception 'revision_withdrawn'; end if;
    if v_revision.status<>'approved' then raise exception 'revision_not_approved'; end if;
    insert into private.observer_final_versions(team_id,phase_id,revision_id,chosen_by)
      values(v_team,p_phase,p_revision,auth.uid())
      on conflict(team_id,phase_id) do update set revision_id=excluded.revision_id,chosen_by=excluded.chosen_by,chosen_at=now();
  end if;
  perform private.audit('observer.final_version',jsonb_build_object('phase_id',p_phase,'revision_id',p_revision));
  return private.observer_final_version_state(v_team,p_phase);
end $$;

-- Captain only, phase open, explicit choice required. p_revision (optional) must equal the current
-- choice, so a teammate's concurrent change is never frozen unseen. Freezing again is a no-op.
create or replace function public.observer_freeze_final_version(p_phase uuid, p_revision uuid default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_team uuid; v_leader uuid; v_phase public.phases; v_final private.observer_final_versions;
begin
  perform private.assert_not_banned();
  select team_id into v_team from public.profiles where id=auth.uid();
  if v_team is null then raise exception 'team_required'; end if;
  select leader_id into v_leader from public.teams where id=v_team for update;
  if v_leader is distinct from auth.uid() then raise exception 'captain_required'; end if;
  select * into v_phase from public.phases where id=p_phase;
  if not found or not private.observer_final_phase(p_phase) or not public.observer_phase_visible(p_phase) then
    raise exception 'final_phase_invalid'; end if;
  if v_phase.ends_at is not null and now()>=v_phase.ends_at then raise exception 'final_version_locked'; end if;
  select f.* into v_final from private.observer_final_versions f
    join public.observer_revisions r on r.id=f.revision_id join public.observer_projects j on j.id=r.project_id
    where f.team_id=v_team and f.phase_id=p_phase and j.team_id=v_team and r.status='approved' and r.archived_at is null
    for update of f;
  if not found then raise exception 'final_version_not_chosen'; end if;
  if p_revision is not null and v_final.revision_id<>p_revision then raise exception 'final_version_changed'; end if;
  if v_final.frozen_at is null then
    update private.observer_final_versions set frozen_at=now(), frozen_by=auth.uid()
      where team_id=v_team and phase_id=p_phase;
    perform private.audit('observer.final_version_freeze',
      jsonb_build_object('phase_id',p_phase,'revision_id',v_final.revision_id,'team_id',v_team));
  end if;
  return private.observer_final_version_state(v_team,p_phase);
end $$;

revoke all on function public.observer_freeze_final_version(uuid, uuid) from public, anon;
grant execute on function public.observer_freeze_final_version(uuid, uuid) to authenticated, service_role;
