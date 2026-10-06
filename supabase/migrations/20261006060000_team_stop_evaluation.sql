-- 停止评测: a team can stop its own started evaluation (observer_cancel_batch(p_batch, p_running=>true)).
-- Every unfinished card is cancelled ('cancelled by team', never scored) and its live jobs fail with
-- 'team_cancel'; then the evaluation is finalized: a cancelled A-D card fails it, and with A-D all scored
-- (only A1-D1 stopped) it ends 'scored' with the A-D mean (online board; not complete for the super board).
-- A stopped evaluation is not refunded (a queued one is still cancelled and refunded as before).
-- team_cancel job failures are not a platform failure: no health strike or cooldown for the organization.
-- Without p_running the function behaves as before (older CLIs: 'evaluation_started').
drop function if exists public.observer_cancel_batch(uuid);
CREATE OR REPLACE FUNCTION public.observer_cancel_batch(p_batch uuid, p_running boolean DEFAULT false)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare v public.observer_batches; v_admin boolean; v_ids uuid[]; v_done uuid[]:='{}'; v_stopped uuid[]:='{}'; v_id uuid; v_runs uuid[];
begin
  perform private.assert_not_banned();
  v_admin:=public.is_admin();
  select * into v from public.observer_batches where id=p_batch;
  if not found or v.purpose<>'formal' or not (v_admin or public.observer_team(v.team_id)) then
    raise exception 'evaluation_not_found'; end if;
  if not v_admin and exists(select 1 from public.observer_phase_settings s where s.phase_id=v.phase_id and s.sealed) then
    raise exception 'evaluation_not_cancellable'; end if;
  -- This evaluation and, in a self-check set, the set's other unfinished members.
  select array_agg(b.id order by b.id) into v_ids from public.observer_batches b
    where b.id=p_batch or (v.repeat_group is not null and b.repeat_group=v.repeat_group
      and b.purpose='formal' and b.status in ('queued','running'));
  -- Runs first (the dispatcher's lock), then the evaluations, each in id order.
  perform 1 from public.observer_runs where batch_id=any(v_ids) order by id for update;
  perform 1 from public.observer_batches where id=any(v_ids) order by id for update;
  select * into v from public.observer_batches where id=p_batch;
  if v.status='cancelled' then
    return jsonb_build_object('batch_id',p_batch,'status','cancelled','cancelled','[]'::jsonb); end if;
  if v.status not in ('queued','running') then raise exception 'evaluation_finished'; end if;
  foreach v_id in array v_ids loop
    -- Not started: unfinished, every card still queued and no card with a live job.
    if exists(select 1 from public.observer_batches b where b.id=v_id and b.status in ('queued','running'))
      and not exists(select 1 from public.observer_runs r where r.batch_id=v_id and r.status<>'queued')
      and not exists(select 1 from private.observer_jobs j join public.observer_runs r on r.id=j.run_id
        where r.batch_id=v_id and j.status in ('queued','dispatched','claimed'))
    then
      update public.observer_runs set status='cancelled',finished_at=now() where batch_id=v_id and status='queued';
      delete from private.observer_run_leases l using public.observer_runs r where r.id=l.run_id and r.batch_id=v_id;
      update public.observer_batches set status='cancelled',finished_at=now(),quota_refunded=true where id=v_id;
      v_done:=v_done||v_id;
    elsif v_id=p_batch and not coalesce(p_running,false) then
      raise exception 'evaluation_started';
    elsif v_id=p_batch then
      -- 停止评测: a started evaluation. Its unfinished cards are cancelled (never scored) and their live
      -- jobs fail with 'team_cancel' (no org health strike, no automatic requeue); not refunded.
      with c as (update public.observer_runs set status='cancelled',error='cancelled by team',finished_at=now()
          where batch_id=v_id and status in ('queued','starting','ready','running','awaiting_csv') returning id)
        select coalesce(array_agg(id),'{}') into v_runs from c;
      update private.observer_jobs set status='failed',error='team_cancel',finished_at=now()
        where run_id=any(v_runs) and status in ('queued','dispatched','claimed');
      delete from private.observer_run_leases where run_id=any(v_runs);
      update private.observer_sessions set expires_at=least(expires_at,now()) where run_id=any(v_runs);
      -- A cancelled A-D card fails the evaluation; with A-D all scored it ends 'scored' with their mean.
      perform private.observer_finalize_batch(v_id);
      v_stopped:=v_stopped||v_id;
    end if;
  end loop;
  perform private.audit('observer.cancel_batch',jsonb_build_object('batch_id',p_batch,'team_id',v.team_id,
    'repeat_group',v.repeat_group,'cancelled',to_jsonb(v_done),'stopped',to_jsonb(v_stopped),'by_admin',v_admin and not public.observer_team(v.team_id)));
  if cardinality(v_stopped)>0 then
    return jsonb_build_object('batch_id',p_batch,'status',(select status from public.observer_batches where id=p_batch),
      'cancelled',to_jsonb(v_done),'stopped',to_jsonb(v_stopped)); end if;
  return jsonb_build_object('batch_id',p_batch,'status','cancelled','cancelled',to_jsonb(v_done));
end $function$
;

revoke all on function public.observer_cancel_batch(uuid,boolean) from public,anon;
grant execute on function public.observer_cancel_batch(uuid,boolean) to authenticated,service_role;

CREATE OR REPLACE FUNCTION private.observer_finalize_batch(p_batch uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
begin
  perform 1 from public.observer_batches where id=p_batch for update;
  if exists(select 1 from public.observer_runs r where r.batch_id=p_batch and private.observer_run_fails_batch(r.id)) then
    -- Decided once, when the batch fails: later runs of a failed batch no longer count.
    update public.observer_batches set status='failed',finished_at=now(),
      quota_refunded=not exists(select 1 from public.observer_runs r where r.batch_id=p_batch
        and private.observer_participant_failure(r.id))
        -- stopped by the team while running (observer_cancel_batch): not refunded
        and not exists(select 1 from public.observer_runs r where r.batch_id=p_batch and r.error='cancelled by team')
      where id=p_batch and status in ('queued','running');
    -- Two stages: a failed stage 1 (A-D) never starts stage 2 (A1-D1); requeue_platform_failures
    -- queues these again if it reopens the evaluation.
    update public.observer_runs r set status='cancelled',error='stage1_failed',finished_at=now()
      from public.observer_batches b, public.scenarios s
      where b.id=p_batch and b.staged and b.status='failed' and r.batch_id=p_batch and s.id=r.scenario_id
        and r.status='queued' and private.observer_extra_card(s.slug);
  elsif exists(select 1 from public.observer_runs where batch_id=p_batch)
    and not exists(select 1 from public.observer_runs where batch_id=p_batch and status not in ('scored','failed','cancelled')) then
    -- Only scored cards, (hidden final) the team's own failed cards and failed added cards are
    -- left (a failed or cancelled A-D card failed the batch above); those count as 0.
    update public.observer_batches set status='scored',score=private.observer_batch_score(p_batch),finished_at=now()
      where id=p_batch and status in ('queued','running');
  end if;
end $function$
;

CREATE OR REPLACE FUNCTION private.observer_platform_failure(v private.observer_jobs)
 RETURNS boolean
 LANGUAGE sql
 IMMUTABLE
AS $function$
  select v.status='failed' and v.claimed_at is not null and v.kind in ('engine','execute','score','prepare')
    and coalesce(v.result->'diagnostics'->>'code','') not in ('project_error','project_operation_failed')
    and coalesce(v.error,'')<>'team_cancel'
$function$
;
