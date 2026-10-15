-- Hidden final progress for the site, while the evaluation runs: counts only, never scores or card
-- contents. Teams that are not hidden and have a final version (chosen, else the version of their best
-- scored evaluation, as private.observer_final_version_state) count; each runs repeat_runs evaluations
-- of every card. A team's current set is its evaluations that were not replaced (superseded_at).
-- The caller's own team also gets each card's state (my_cards): done (all repeats finished), running, waiting;
-- a team that has no evaluation in the hidden phase yet (relay teams wait their turn) gets none.
create or replace function private.observer_final_progress_compute()
returns jsonb language sql stable security definer set search_path to 'public','pg_temp' as $$
  with ph as (select p.id from public.phases p where p.slug='final-hidden' and p.is_active),
  src as (select q.online_phase id from private.observer_queue_config q where q.id),
  per as (select greatest(1,coalesce(c.repeat_runs,1))*(select count(*) from public.phase_scenarios s where s.phase_id=ph.id) n
    from ph join public.observer_phase_settings c on c.phase_id=ph.id),
  finalists as (select t.id from public.teams t where not t.is_hidden and (
      exists(select 1 from private.observer_final_versions f join public.observer_revisions r on r.id=f.revision_id
        join public.observer_projects j on j.id=r.project_id
        where f.team_id=t.id and f.phase_id=(select id from src) and j.team_id=t.id and r.status='approved' and r.archived_at is null)
      or exists(select 1 from public.observer_batches b where b.team_id=t.id and b.phase_id=(select id from src)
        and b.purpose='formal' and b.status='scored' and b.revision_id is not null and b.score is not null))),
  runs as (select b.team_id, r.scenario_id, r.status from public.observer_runs r join public.observer_batches b on b.id=r.batch_id
    where b.phase_id=(select id from ph) and b.purpose='formal' and b.superseded_at is null)
  select case when not exists(select 1 from ph) then null else jsonb_build_object(
    'teams_total',(select count(*) from finalists),
    'teams_done',(select count(*) from finalists f where (select count(*) filter (where r.status in ('scored','failed')) from runs r where r.team_id=f.id)>=(select n from per)),
    'runs_total',(select count(*) from finalists)*(select n from per),
    'runs_done',(select count(*) from runs r join finalists f on f.id=r.team_id where r.status in ('scored','failed')),
    'runs_running',(select count(*) from runs r join finalists f on f.id=r.team_id where r.status in ('starting','ready','running')),
    'updated_at',now()) end
$$;

create table if not exists private.final_progress_cache(id boolean primary key default true check (id), payload jsonb, computed_at timestamptz not null);
revoke all on private.final_progress_cache from public, anon, authenticated;

-- The site polls this once a minute per visitor: the overall counts are shared for 30 seconds;
-- the caller's own cards are read for its team only.
create or replace function public.observer_final_progress()
returns jsonb language plpgsql security definer set search_path to 'public','pg_temp' as $$
declare v jsonb; v_team uuid:=private.observer_team_of(auth.uid()); v_phase uuid;
begin
  select payload into v from private.final_progress_cache where id and computed_at>now()-interval '30 seconds';
  if not found then
    v:=private.observer_final_progress_compute();
    insert into private.final_progress_cache(id,payload,computed_at) values(true,v,now())
      on conflict(id) do update set payload=excluded.payload, computed_at=excluded.computed_at;
  end if;
  if v is null or v_team is null then return v; end if;
  select p.id into v_phase from public.phases p where p.slug='final-hidden' and p.is_active;
  if exists(select 1 from public.teams t where t.id=v_team and t.is_hidden) then return v; end if;
  return v||jsonb_build_object('my_cards',(select jsonb_agg(jsonb_build_object('card',x.card,'state',x.state) order by x.card) from (
    select upper(right(sc.slug,1)) card,
      case when count(r.status)=0 then 'waiting'
        when bool_and(r.status in ('scored','failed')) then 'done'
        when bool_or(r.status in ('starting','ready','running')) then 'running' else 'waiting' end state
    from public.phase_scenarios ps join public.scenarios sc on sc.id=ps.scenario_id
    left join (select r.scenario_id, r.status from public.observer_runs r join public.observer_batches b on b.id=r.batch_id
      where b.team_id=v_team and b.phase_id=v_phase and b.purpose='formal' and b.superseded_at is null) r on r.scenario_id=sc.id
    where ps.phase_id=v_phase group by sc.id, sc.slug) x
    where exists(select 1 from public.observer_batches b where b.team_id=v_team and b.phase_id=v_phase)));
end $$;
revoke all on function public.observer_final_progress() from public;
grant execute on function public.observer_final_progress() to anon, authenticated;
revoke all on function private.observer_final_progress_compute() from public, anon, authenticated;
