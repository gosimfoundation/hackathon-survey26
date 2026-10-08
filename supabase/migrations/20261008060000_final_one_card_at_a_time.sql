-- Hidden final: a team runs one card at a time (owner decision 2026-10-08). The repeats of
-- that card still start together (20261004120000); the team's next card, in creation order
-- (E, F, G, H), starts once none of its other cards is starting or running and no
-- earlier-created run of another card still waits. Teams run side by side. At most
-- repeat_runs programs of a team, and so of one model key, run at the same time.
-- Only queued runs are affected; other phases (repeat_runs = 1) are unchanged.
-- Applied to production 2026-10-08 06:37Z after a rolled-back test of the transitions.

CREATE OR REPLACE FUNCTION public.observer_pending_runs(p_limit integer DEFAULT 5)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare r record; result jsonb:='[]'; v_lease uuid; v_minutes integer; v_old private.observer_run_leases;
  v_cap integer:=greatest(1,least(coalesce(p_limit,5),10)); v_count integer:=0; v_group text; v_max integer;
begin
  -- Scheduling leases past the retry budget are parked, never failed: the run
  -- stays 'queued' for the contestant and an incident pages the organizers.
  -- Waiting for a runner does not use the budget: it needs repeated attempts too.
  for r in select run.id,run.batch_id,l.attempts,l.first_leased_at from public.observer_runs run
    join private.observer_run_leases l on l.run_id=run.id
    where run.status='queued' and l.paused_at is null and l.expires_at<=now()
      and now()-l.first_leased_at>interval '2 hours' and l.attempts>=8
    for update of run skip locked limit 100
  loop
    update private.observer_run_leases set paused_at=now() where run_id=r.id;
    perform private.observer_raise_incident('run',r.id,'run_schedule_retry_budget_exhausted',
      jsonb_build_object('attempts',r.attempts,'batch_id',r.batch_id));
  end loop;
  -- Capacity gate: while enough evaluation jobs already wait for a runner, further runs wait
  -- here (queued, by tier) instead of in the runner queues.
  select q.max_waiting_jobs into v_max from private.observer_queue_config q where q.id;
  if v_max is not null then
    v_cap:=least(v_cap,greatest(0,v_max-(select count(*) from private.observer_jobs j
      where j.status in ('queued','dispatched') and j.kind in ('engine','execute') and j.expires_at>now())::integer));
    if v_cap=0 then return result; end if;
  end if;
  -- Serialize reservations, including first insert, on the public run row. A
  -- crashed scheduler leaves a short lease, never a half-open session.
  for r in select run.id,b.user_id,b.mode,
      case when b.purpose='preview' then least(c.runtime_seconds,300) else c.runtime_seconds end as runtime_seconds,
      s.storage_path,s.digest as scenario_digest,
      m.archive_ref,m.digest as materialized_digest,rev.manifest,
      -- Repeated evaluations that must start together: the same card of one team's evaluations.
      case when c.repeat_runs>1 and b.purpose='formal' then b.team_id::text||'/'||run.scenario_id::text end as start_group
    from public.observer_runs run join public.observer_batches b on b.id=run.batch_id
    join public.observer_phase_settings c on c.phase_id=b.phase_id
    join private.observer_scenario_bundles s on s.scenario_id=run.scenario_id
    join public.profiles p on p.id=b.user_id and not p.is_banned and p.team_id=b.team_id
    left join public.observer_revisions rev on rev.id=b.revision_id
    left join private.observer_materializations m on m.revision_id=rev.id
    left join private.observer_run_leases l on l.run_id=run.id
    where run.status='queued' and b.purpose in ('formal','preview') and b.status in ('queued','running')
      and ((b.mode='local' and c.local_sessions_enabled) or
        (b.mode='project' and c.projects_enabled and m.revision_id is not null and
          ((b.purpose='formal' and rev.status='approved') or (b.purpose='preview' and rev.status='preparing'))))
      -- A local user starts one scenario at a time. Do not spend hosted engine
      -- minutes waiting for the other scenarios while their first CLI is busy.
      and (b.mode<>'local' or not exists(select 1 from public.observer_runs other
        where other.batch_id=run.batch_id and other.id<>run.id and
          (other.status in ('starting','ready','running') or
            (other.status='queued' and (other.created_at,other.id)<(run.created_at,run.id)))))
      and (l.run_id is null or (l.expires_at<=now() and l.paused_at is null))
      -- Two stages: an A1-D1 card of a staged evaluation starts only once all its A-D cards finished.
      and not (b.staged and private.observer_stage2_waiting(run.id))
      -- The evaluations of one self-check set run one after another; a team's other evaluations
      -- run side by side (up to max_active_evaluations, enforced on creation). The hidden final's
      -- repeats start together (start_group), one card at a time (below).
      and (b.purpose<>'formal' or c.repeat_runs>1 or b.repeat_group is null or not exists(select 1 from public.observer_batches earlier
        where earlier.repeat_group=b.repeat_group and earlier.purpose='formal'
          and earlier.id<>b.id and earlier.status in ('queued','running')
          and (earlier.created_at,earlier.id)<(b.created_at,b.id)))
      -- Hidden final: one card of a team at a time. Its repeats of that card start together;
      -- the next card (creation order) starts only once none of the team's other cards is
      -- starting or running and no earlier-created run of another card still waits.
      and (b.purpose<>'formal' or c.repeat_runs<=1 or not exists(select 1 from public.observer_runs other
        join public.observer_batches ob on ob.id=other.batch_id
        where ob.team_id=b.team_id and ob.phase_id=b.phase_id and ob.purpose='formal'
          and ob.status in ('queued','running') and other.scenario_id<>run.scenario_id
          and (other.status in ('starting','ready','running') or
            (other.status='queued' and (other.created_at,other.id)<(run.created_at,run.id)))))
    -- Ranked teams first (private.observer_queue_tier), FIFO within a tier.
    order by private.observer_queue_tier(b.team_id),run.created_at,run.id for update of run skip locked limit 40
  loop
    -- Up to the cap, but a start group (created adjacently) is never split between passes.
    exit when v_count>=v_cap and (r.start_group is null or r.start_group is distinct from v_group);
    -- The join snapshot may predate a concurrently committed first lease even
    -- though this row lock was acquired afterwards. Re-read under the lock.
    select * into v_old from private.observer_run_leases where run_id=r.id;
    if found and (v_old.expires_at>now() or v_old.paused_at is not null) then continue; end if;
    v_lease:=gen_random_uuid();
    v_minutes:=case when found then (least(20,2^greatest(v_old.attempts,1)))::int else 2 end;
    insert into private.observer_run_leases(run_id,lease,expires_at)
      values(r.id,v_lease,now()+(v_minutes||' minutes')::interval)
      on conflict(run_id) do update set lease=excluded.lease,expires_at=excluded.expires_at,
        attempts=private.observer_run_leases.attempts+1;
    result:=result || jsonb_build_array((to_jsonb(r)-'start_group')||jsonb_build_object('lease',v_lease));
    v_count:=v_count+1; v_group:=r.start_group;
  end loop;
  return result;
end $function$;
