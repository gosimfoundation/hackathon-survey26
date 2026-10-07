-- Free Play (娱乐赛, slug 'after-party'): an unscored phase on the online cards (A-D and A1-D1)
-- that opens when the online phase freezes (online.ends_at, 2026-10-07 21:59:59 UTC) and stays open.
-- It counts for nothing: counts_for_final=false, slug<>'online', so it is never a final-version phase
-- (private.observer_final_phase), never a hidden-final source, and its batches never enter the online
-- board or the online final-version default (both are keyed on the online phase id).
-- Additive only: a new phase row, its settings and card links, and current_competition() answers
-- fun_phase_id once the phase has started.
insert into public.phases(id,slug,name_en,name_zh,description_en,description_zh,sort_order,starts_at,ends_at,
    allow_results,allow_agents,daily_limit,leaderboard_mode,counts_for_final,is_active)
values('a0f7e9a2-5d3c-4b1e-9f60-2b7c1d8e4a01','after-party','Free Play','娱乐赛',
  'Opens when the online competition closes and stays open after the event. Same cards as the online competition: A, B, C, D and A1, B1, C1, D1. Evaluate any of your confirmed versions or submit new ones; 50 evaluations per team per day (failures caused by the platform are not counted); 900 s per card; model calls use your team''s own model API key only. Separate board, just for fun: no awards, no part in the final, and it never changes your online final version or the online board. New evaluations may be paused while the organizers run the hidden-card final.',
  '正式赛结束后开放，比赛结束后也持续开放。任务卡与正式赛相同：A、B、C、D 和 A1、B1、C1、D1。可以评测已确认的任何版本，也可以提交新版本；每队每天 50 次，因平台原因失败的不计次数；每张任务卡运行时限 900 秒；调用模型只能使用本队自己的模型 API 密钥。单独榜单，仅供娱乐：不设奖项，不计入决赛，也不会改变正式赛的最终版本和正式赛排行榜。主办方进行隐藏卡决赛评测期间，新的评测可能暂停。',
  55,'2026-10-07 21:59:59+00',null,false,false,4,'live',false,true)
on conflict (id) do nothing;

insert into public.observer_phase_settings(phase_id,projects_enabled,local_sessions_enabled,runtime_seconds,daily_batches,
    model_token_limit,model_call_limit,model_concurrency,access_team_id,colocated,sealed,board_layout,repeat_runs,max_active_evaluations)
values('a0f7e9a2-5d3c-4b1e-9f60-2b7c1d8e4a01',true,false,900,50,1000000000,100000,4,null,true,false,'cards_overall',1,10)
on conflict (phase_id) do nothing;

insert into public.phase_scenarios(phase_id,scenario_id)
select 'a0f7e9a2-5d3c-4b1e-9f60-2b7c1d8e4a01',ps.scenario_id from public.phase_scenarios ps
  join public.phases p on p.id=ps.phase_id join public.scenarios s on s.id=ps.scenario_id
  where p.slug='online' and s.slug in ('v4-a','v4-b','v4-c','v4-d','v4-a1-v5','v4-b1-v5','v4-c1-v5','v4-d1-v5')
on conflict do nothing;

-- Like online: runs may use the public runner pool (organizers switch it off with observer_set_public_pool_phase).
insert into private.observer_public_pool_phases(phase_id,enabled)
values('a0f7e9a2-5d3c-4b1e-9f60-2b7c1d8e4a01',true) on conflict (phase_id) do nothing;

-- Model calls in Free Play use the team's own key whatever the site mode.
create or replace function private.observer_personal_models_only(p_run uuid)
returns boolean language sql stable security definer set search_path = public, pg_temp as $$
  select exists(select 1 from public.observer_runs r join public.observer_batches b on b.id=r.batch_id
    join public.phases p on p.id=b.phase_id where r.id=p_run and (p.counts_for_final or p.slug='online'
      or p.slug like 'observer-acceptance-%' or p.slug='practice-projects' or p.slug='after-party'
      -- Preparation uses its own restricted phase, even during the competition.
      -- That shared phase must not silently spend organizer credits either.
      or exists(select 1 from private.observer_site_mode where id and mode='competition')))
$$;

-- fun_phase_id: the Free Play phase once it has started (also while new evaluations are paused, so its
-- board and records stay one click away).
create or replace function public.current_competition()
returns jsonb language sql stable security definer set search_path = public, pg_temp as $$
  with m as (select m.mode,coalesce(m.phase_id,(select id from public.phases
      where slug=case when m.mode='practice' then 'practice' else 'online' end)) phase_id
    from private.observer_site_mode m where m.id),
  practice as (select p.id from public.phases p join public.observer_phase_settings s on s.phase_id=p.id
    where p.slug='practice-projects' and p.is_active and s.projects_enabled and s.access_team_id is null
      and (p.starts_at is null or now()>=p.starts_at) and (p.ends_at is null or now()<p.ends_at)),
  extra as (select p.id from private.observer_extra_phase x join public.phases p on p.id=x.phase_id
      join public.observer_phase_settings s on s.phase_id=p.id
    where x.id and p.is_active and s.projects_enabled
      and (s.access_team_id is null or exists(select 1 from public.profiles u where u.id=auth.uid()
        and not u.is_banned and u.team_id=s.access_team_id))
      and (p.starts_at is null or now()>=p.starts_at) and (p.ends_at is null or now()<p.ends_at)),
  fun as (select p.id from public.phases p join public.observer_phase_settings s on s.phase_id=p.id
    where p.slug='after-party' and p.is_active and not s.sealed
      and (s.access_team_id is null or exists(select 1 from public.profiles u where u.id=auth.uid()
        and not u.is_banned and u.team_id=s.access_team_id))
      and p.starts_at is not null and now()>=p.starts_at and (p.ends_at is null or now()<p.ends_at))
  select jsonb_build_object('mode',m.mode,'phase_id',m.phase_id)
    || coalesce((select case when m.mode='practice' then jsonb_build_object('project_phase_id',p.id)
        else jsonb_build_object('practice_phase_id',p.id)
          || case when exists(select 1 from public.phases o where o.id=m.phase_id and o.ends_at is not null and now()>=o.ends_at)
             then jsonb_build_object('project_phase_id',p.id) else '{}'::jsonb end end
      from practice p),'{}'::jsonb)
    || coalesce((select jsonb_build_object('extra_phase_id',e.id) from extra e),'{}'::jsonb)
    || coalesce((select jsonb_build_object('fun_phase_id',f.id) from fun f),'{}'::jsonb)
  from m
$$;
