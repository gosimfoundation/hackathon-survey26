-- Open track for the four new AOH tasks (2026-10-13). Additive only: new tables, one view and new
-- functions; no existing table, function, policy or phase setting is touched.
--
-- Rules: anyone signed in may submit (no team needed), choose any subset of the active tasks, and
-- each chosen task is evaluated once on its fixed hidden seed list (no 3-run average, no "all tasks
-- at once"). A participant may bring their own OpenAI-compatible model API; the key arrives already
-- encrypted in the browser with the executor's public key (RSA-OAEP), so the database never holds a
-- usable key and only the executor job can decrypt it.
--
-- Evaluation is split across two machines (open_track/, .github/workflows/open-worker.yml):
--   engine   (trusted): holds the hidden bundle (salt + hidden wording pools), runs the environment,
--            never runs participant code;
--   executor (untrusted side): runs the participant's agent in a network-less container next to a
--            metered model proxy, never sees hidden seeds or wording pools.
-- They exchange only public protocol messages through private.open_messages.

create table public.open_problems (
  id text primary key check (id ~ '^[a-z][a-z0-9_]{1,40}$'),
  title_zh text not null,
  title_en text not null,
  version text not null,
  -- Hidden seed indices evaluated for every submission; the score is their mean.
  seed_indices int[] not null check (cardinality(seed_indices) between 1 and 50),
  wallclock_seconds int not null default 600 check (wallclock_seconds between 30 and 7200),
  kit_url text not null default '',
  active boolean not null default true,
  sort int not null default 0
);

create table public.open_submissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  problems text[] not null check (cardinality(problems) between 1 and 10),
  zip_sha256 text not null check (zip_sha256 ~ '^[0-9a-f]{64}$'),
  zip_bytes int not null check (zip_bytes between 22 and 2097152),
  uses_model boolean not null default false,
  model_base text not null default '',
  model_name text not null default '',
  key_hint text not null default '' check (key_hint ~ '^[!-~]{0,4}$'),
  note text not null default '' check (char_length(note) <= 200),
  status text not null default 'queued' check (status in ('queued','running','done','failed','cancelled')),
  created_at timestamptz not null default clock_timestamp()
);
create index open_submissions_user on public.open_submissions(user_id, created_at desc);

-- One row per (submission, task, hidden seed index).
create table public.open_runs (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references public.open_submissions(id) on delete cascade,
  problem_id text not null references public.open_problems(id),
  seed_index int not null,
  status text not null default 'queued' check (status in ('queued','running','done','failed','cancelled')),
  engine_worker text,
  engine_claimed_at timestamptz,
  exec_worker text,
  exec_claimed_at timestamptz,
  exec_seen_at timestamptz,  -- executor heartbeat (open_exec_alive)
  attempts int not null default 0,
  -- attempts given back by the engine before the agent started (not counted against the 3-attempt cap)
  releases int not null default 0,
  total double precision,
  report jsonb,
  error text not null default '',
  finished_at timestamptz,
  unique (submission_id, problem_id, seed_index)
);
create index open_runs_queue on public.open_runs(status, engine_claimed_at);

-- Never readable by participants.
create table private.open_submission_files (
  submission_id uuid primary key references public.open_submissions(id) on delete cascade,
  zip bytea not null,
  -- RSA-OAEP(SHA-256) ciphertext of the model API key, base64; '' when no model is used.
  key_ciphertext text not null default '' check (length(key_ciphertext) <= 4096)
);

-- Full score report and decision log of a hidden seed: organizers only. The seeds are fixed, so per-event
-- details (which candidate was real, when a fault happened) would leak the hidden test to later submissions;
-- participants get only the numeric summary in open_runs.report.
create table private.open_run_details (
  run_id uuid not null references public.open_runs(id) on delete cascade,
  attempt int not null,
  report jsonb not null,
  decisions jsonb not null default '[]'::jsonb,
  agent_log text not null default '',
  created_at timestamptz not null default clock_timestamp(),
  primary key (run_id, attempt)
);

create table private.open_messages (
  run_id uuid not null references public.open_runs(id) on delete cascade,
  -- open_runs.attempts at the time: a requeued run starts a fresh exchange, earlier ones are kept.
  attempt int not null,
  direction text not null check (direction in ('to_agent','from_agent','usage')),
  seq int not null,
  body jsonb not null,
  created_at timestamptz not null default clock_timestamp(),
  primary key (run_id, attempt, direction, seq)
);

-- Model APIs a participant may bring: known providers only. With fixed hidden seeds, a participant-run
-- endpoint could record the hidden observations an agent sends; providers do not hand prompts back.
create table public.open_model_hosts (
  host text primary key check (host ~ '^[a-z0-9.-]+$'),
  note text not null default ''
);
alter table public.open_model_hosts enable row level security;
revoke all on public.open_model_hosts from anon, authenticated;
grant select on public.open_model_hosts to anon, authenticated;
create policy open_model_hosts_read on public.open_model_hosts for select using (true);
insert into public.open_model_hosts(host, note) values
  ('api.openai.com', 'OpenAI'), ('api.anthropic.com', 'Anthropic (OpenAI-compatible endpoint)'),
  ('api.deepseek.com', 'DeepSeek'), ('api.moonshot.cn', 'Moonshot'), ('api.moonshot.ai', 'Moonshot'),
  ('api.kimi.com', 'Kimi'), ('open.bigmodel.cn', 'Zhipu'), ('api.z.ai', 'Z.ai'),
  ('dashscope.aliyuncs.com', 'Alibaba Qwen'), ('dashscope-intl.aliyuncs.com', 'Alibaba Qwen'),
  ('generativelanguage.googleapis.com', 'Google Gemini (OpenAI-compatible)'), ('api.mistral.ai', 'Mistral'),
  ('api.groq.com', 'Groq'), ('openrouter.ai', 'OpenRouter'), ('api.siliconflow.cn', 'SiliconFlow'),
  ('api.minimax.chat', 'MiniMax'), ('api.minimaxi.com', 'MiniMax'), ('ark.cn-beijing.volces.com', 'Volcengine Ark');

-- Participant access: read own rows only; every write goes through the functions below.
alter table public.open_problems enable row level security;
alter table public.open_submissions enable row level security;
alter table public.open_runs enable row level security;
revoke all on public.open_problems, public.open_submissions, public.open_runs from anon, authenticated;
grant select on public.open_problems to anon, authenticated;
grant select on public.open_submissions, public.open_runs to authenticated;
create policy open_problems_read on public.open_problems for select using (true);
create policy open_submissions_own on public.open_submissions for select using (user_id = auth.uid());
create policy open_runs_own on public.open_runs for select using (
  exists (select 1 from public.open_submissions s where s.id = submission_id and s.user_id = auth.uid()));
revoke all on private.open_submission_files, private.open_messages, private.open_run_details from public, anon, authenticated;

-- Per submission and task: mean over the task's seeds, only once every seed has finished.
create view public.open_submission_scores with (security_invoker = true) as
  select r.submission_id, r.problem_id, s.user_id, count(*) as seeds,
         count(*) filter (where r.status = 'done') as seeds_done,
         case when count(*) = count(*) filter (where r.status = 'done') then avg(r.total) end as mean_total,
         max(r.finished_at) as finished_at
    from public.open_runs r join public.open_submissions s on s.id = r.submission_id
   group by r.submission_id, r.problem_id, s.user_id;
revoke all on public.open_submission_scores from anon, authenticated;
grant select on public.open_submission_scores to authenticated;

-- Public board: each participant's best complete submission per task. Display name is the
-- nickname, else an anonymous handle; no email, real name or team is exposed.
create function public.open_leaderboard()
returns table (problem_id text, player text, best_total double precision, uses_model boolean,
               submissions bigint, achieved_at timestamptz)
language sql stable security definer set search_path = public, pg_temp as $$
  with scored as (
    select r.submission_id, r.problem_id, s.user_id, s.uses_model, avg(r.total) as mean_total,
           max(r.finished_at) as finished_at
      from public.open_runs r join public.open_submissions s on s.id = r.submission_id
     where s.status <> 'cancelled'
     group by r.submission_id, r.problem_id, s.user_id, s.uses_model
    having count(*) = count(*) filter (where r.status = 'done')
  ), best as (
    select distinct on (problem_id, user_id) problem_id, user_id, mean_total, uses_model, finished_at,
           count(*) over (partition by problem_id, user_id) as n
      from scored order by problem_id, user_id, mean_total desc, finished_at
  )
  select b.problem_id,
         coalesce(nullif(p.nickname, ''), 'player-' || substr(md5(b.user_id::text), 1, 6)),
         b.mean_total, b.uses_model, b.n, b.finished_at
    from best b join public.profiles p on p.id = b.user_id
   where not p.is_banned
   order by b.problem_id, b.mean_total desc, b.finished_at
$$;
revoke all on function public.open_leaderboard() from public;
grant execute on function public.open_leaderboard() to anon, authenticated;

-- Submit: a ZIP (agent.py at its root, standard library only) for any subset of the active tasks.
-- Limits: 2 MB, 10 submissions per day, at most 2 unfinished submissions at a time.
create function public.open_submit(p_problems text[], p_zip_base64 text, p_model_base text default '',
  p_model_name text default '', p_key_ciphertext text default '', p_key_hint text default '', p_note text default '')
returns uuid language plpgsql security definer set search_path = public, pg_temp as $$
declare v_uid uuid := auth.uid(); v_zip bytea; v_id uuid; v_p text; v_uses boolean; v_seed int;
begin
  if v_uid is null then raise exception 'sign_in_required'; end if;
  if not exists (select 1 from public.profiles where id = v_uid and not is_banned) then raise exception 'not_allowed'; end if;
  if p_problems is null or cardinality(p_problems) = 0
     or (select count(distinct x) from unnest(p_problems) x) <> cardinality(p_problems)
     or exists (select 1 from unnest(p_problems) x where not exists
                (select 1 from public.open_problems o where o.id = x and o.active)) then
    raise exception 'invalid_problems';
  end if;
  begin
    v_zip := decode(p_zip_base64, 'base64');
  exception when others then raise exception 'invalid_zip';
  end;
  if v_zip is null or length(v_zip) < 22 or length(v_zip) > 2097152 or substring(v_zip from 1 for 2) <> '\x504b'::bytea then
    raise exception 'invalid_zip';
  end if;
  v_uses := coalesce(p_key_ciphertext, '') <> '';
  if v_uses and (p_model_base !~ '^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._~/-]*)?$' or length(p_model_base) > 300
       or p_model_name is null or length(p_model_name) not between 1 and 128 or p_model_name ~ '[[:cntrl:]]'
       or length(p_key_ciphertext) > 4096 or p_key_ciphertext !~ '^[A-Za-z0-9+/]+=*$'
       or coalesce(p_key_hint, '') !~ '^[!-~]{0,4}$') then
    raise exception 'invalid_model';
  end if;
  if v_uses and not exists (select 1 from public.open_model_hosts h
                             where h.host = lower(substring(p_model_base from '^https://([A-Za-z0-9.-]+)'))) then
    raise exception 'model_host_not_allowed';
  end if;
  if char_length(coalesce(p_note, '')) > 200 then raise exception 'invalid_note'; end if;
  -- one submission at a time per user while the limits are checked
  perform 1 from public.profiles where id = v_uid for update;
  if (select count(*) from public.open_submissions where user_id = v_uid
        and created_at > clock_timestamp() - interval '1 day') >= 10 then
    raise exception 'daily_limit';
  end if;
  if (select count(*) from public.open_submissions where user_id = v_uid and status in ('queued','running')) >= 2 then
    raise exception 'too_many_pending';
  end if;
  insert into public.open_submissions(user_id, problems, zip_sha256, zip_bytes, uses_model, model_base, model_name, key_hint, note)
    values (v_uid, p_problems, encode(sha256(v_zip), 'hex'), length(v_zip), v_uses,
            case when v_uses then p_model_base else '' end, case when v_uses then p_model_name else '' end,
            case when v_uses then coalesce(p_key_hint, '') else '' end, coalesce(p_note, ''))
    returning id into v_id;
  insert into private.open_submission_files(submission_id, zip, key_ciphertext)
    values (v_id, v_zip, case when v_uses then p_key_ciphertext else '' end);
  foreach v_p in array p_problems loop
    foreach v_seed in array (select seed_indices from public.open_problems where id = v_p) loop
      insert into public.open_runs(submission_id, problem_id, seed_index) values (v_id, v_p, v_seed);
    end loop;
  end loop;
  return v_id;
end $$;
revoke all on function public.open_submit(text[], text, text, text, text, text, text) from public;
grant execute on function public.open_submit(text[], text, text, text, text, text, text) to authenticated;

-- Cancel an own submission's runs that have not started; finished runs stay.
create function public.open_cancel(p_submission uuid)
returns int language plpgsql security definer set search_path = public, pg_temp as $$
declare n int;
begin
  if not exists (select 1 from public.open_submissions where id = p_submission and user_id = auth.uid()) then
    raise exception 'not_found';
  end if;
  update public.open_runs set status = 'cancelled', finished_at = clock_timestamp()
   where submission_id = p_submission and status = 'queued' and engine_claimed_at is null;
  get diagnostics n = row_count;
  perform private.open_refresh_submission(p_submission);
  return n;
end $$;
revoke all on function public.open_cancel(uuid) from public;
grant execute on function public.open_cancel(uuid) to authenticated;

create function private.open_refresh_submission(p_submission uuid)
returns void language sql security definer set search_path = public, pg_temp as $$
  update public.open_submissions s set status = case
      when not exists (select 1 from public.open_runs r where r.submission_id = s.id and r.status in ('queued','running'))
        then case when exists (select 1 from public.open_runs r where r.submission_id = s.id and r.status = 'done') then 'done'
                  when exists (select 1 from public.open_runs r where r.submission_id = s.id and r.status = 'failed') then 'failed'
                  else 'cancelled' end
      when exists (select 1 from public.open_runs r where r.submission_id = s.id and r.status = 'running') then 'running'
      else 'queued' end
   where s.id = p_submission
$$;

-- ---------------------------------------------------------------- worker side
-- Two roles with disjoint powers. The engine uses the service role; the executor gets its own role
-- (open_executor, a JWT with role=open_executor), so the machine that runs participant code cannot read
-- organizer-only tables, write scores or speak for the engine. Every write is bound to the worker and
-- attempt that claimed the run, so a stale engine or executor can never touch a newer attempt.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'open_executor') then
    create role open_executor nologin;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticator') then
    grant open_executor to authenticator;
  end if;
end $$;
grant usage on schema public to open_executor;


-- Engine: take the oldest queued run. Returns task, seed index, attempt and wall clock; never the agent.
create function public.open_engine_claim(p_worker text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare r public.open_runs; o public.open_problems;
begin
  select * into r from public.open_runs where status = 'queued' and engine_claimed_at is null
   order by (select created_at from public.open_submissions s where s.id = submission_id), problem_id, seed_index
   limit 1 for update skip locked;
  if not found then return null; end if;
  update public.open_runs set status = 'running', engine_worker = p_worker, engine_claimed_at = clock_timestamp(),
         exec_worker = null, exec_claimed_at = null, exec_seen_at = null, attempts = attempts + 1
   where id = r.id returning attempts into r.attempts;
  perform private.open_refresh_submission(r.submission_id);
  select * into o from public.open_problems where id = r.problem_id;
  return jsonb_build_object('run_id', r.id, 'attempt', r.attempts, 'submission_id', r.submission_id, 'problem_id', r.problem_id,
                            'seed_index', r.seed_index, 'wallclock_seconds', o.wallclock_seconds);
end $$;

-- Executor: take a run the engine has started. Returns the agent ZIP and the encrypted key; never seeds.
create function public.open_exec_claim(p_worker text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare r public.open_runs; s public.open_submissions; f private.open_submission_files;
begin
  select * into r from public.open_runs where status = 'running' and exec_claimed_at is null
   order by engine_claimed_at limit 1 for update skip locked;
  if not found then return null; end if;
  update public.open_runs set exec_worker = p_worker, exec_claimed_at = clock_timestamp(), exec_seen_at = clock_timestamp()
   where id = r.id;
  select * into s from public.open_submissions where id = r.submission_id;
  select * into f from private.open_submission_files where submission_id = r.submission_id;
  return jsonb_build_object('run_id', r.id, 'attempt', r.attempts, 'problem_id', r.problem_id, 'zip_base64', encode(f.zip, 'base64'),
                            'zip_sha256', s.zip_sha256, 'uses_model', s.uses_model, 'model_base', s.model_base,
                            'model_name', s.model_name, 'key_ciphertext', f.key_ciphertext);
end $$;

-- Executor heartbeat: true while this worker still owns this attempt of a running run.
create function public.open_exec_alive(p_run uuid, p_worker text, p_attempt int)
returns boolean language plpgsql security definer set search_path = public, pg_temp as $$
begin
  update public.open_runs set exec_seen_at = clock_timestamp()
   where id = p_run and status = 'running' and exec_worker = p_worker and attempts = p_attempt;
  return found;
end $$;

-- Messages. The engine writes to_agent and reads from_agent/usage; the executor the other way round.
create function public.open_engine_post(p_run uuid, p_worker text, p_attempt int, p_seq int, p_body jsonb)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not exists (select 1 from public.open_runs where id = p_run and status = 'running'
                 and engine_worker = p_worker and attempts = p_attempt) then raise exception 'run_not_owned'; end if;
  if octet_length(p_body::text) > 16777216 then raise exception 'message_too_large'; end if;
  insert into private.open_messages(run_id, attempt, direction, seq, body) values (p_run, p_attempt, 'to_agent', p_seq, p_body)
    on conflict do nothing;
end $$;

create function public.open_exec_post(p_run uuid, p_worker text, p_attempt int, p_direction text, p_seq int, p_body jsonb)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if p_direction not in ('from_agent', 'usage') then raise exception 'invalid_direction'; end if;
  if not exists (select 1 from public.open_runs where id = p_run and status = 'running'
                 and exec_worker = p_worker and attempts = p_attempt) then raise exception 'run_not_owned'; end if;
  if octet_length(p_body::text) > 1048576 then raise exception 'message_too_large'; end if;
  insert into private.open_messages(run_id, attempt, direction, seq, body) values (p_run, p_attempt, p_direction, p_seq, p_body)
    on conflict do nothing;
end $$;

create function public.open_engine_fetch(p_run uuid, p_attempt int, p_direction text, p_after int)
returns table (seq int, body jsonb) language sql stable security definer set search_path = public, pg_temp as $$
  select m.seq, m.body from private.open_messages m
   where m.run_id = p_run and m.attempt = p_attempt and m.direction = p_direction
     and p_direction in ('from_agent', 'usage') and m.seq > p_after order by m.seq limit 200
$$;

create function public.open_exec_fetch(p_run uuid, p_worker text, p_attempt int, p_after int)
returns table (seq int, body jsonb) language sql stable security definer set search_path = public, pg_temp as $$
  select m.seq, m.body from private.open_messages m
   where m.run_id = p_run and m.attempt = p_attempt and m.direction = 'to_agent' and m.seq > p_after
     and exists (select 1 from public.open_runs r where r.id = p_run and r.exec_worker = p_worker and r.attempts = p_attempt)
   order by m.seq limit 200
$$;

-- Engine: record the official (replayed) score of its own attempt. p_report is the numeric summary
-- participants see; p_details (full report, decisions, agent log tail) goes to the organizer-only table.
create function public.open_finish(p_run uuid, p_worker text, p_attempt int, p_status text, p_total double precision,
  p_report jsonb, p_error text default '', p_details jsonb default null)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_sub uuid;
begin
  if p_status not in ('done','failed') then raise exception 'invalid_status'; end if;
  update public.open_runs set status = p_status, total = case when p_status = 'done' then p_total end,
         report = p_report, error = left(coalesce(p_error, ''), 2000), finished_at = clock_timestamp()
   where id = p_run and status = 'running' and engine_worker = p_worker and attempts = p_attempt
   returning submission_id into v_sub;
  if v_sub is null then raise exception 'run_not_owned'; end if;
  if p_details is not null then
    insert into private.open_run_details(run_id, attempt, report, decisions, agent_log)
      values (p_run, p_attempt, coalesce(p_details->'report', '{}'::jsonb), coalesce(p_details->'decisions', '[]'::jsonb),
              left(coalesce(p_details->>'agent_log', ''), 65536))
      on conflict do nothing;
  end if;
  perform private.open_refresh_submission(v_sub);
end $$;

-- Engine: give its run back to the queue (no executor started the agent in time); not counted as an attempt.
create function public.open_release(p_run uuid, p_worker text, p_attempt int)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare v_sub uuid;
begin
  update public.open_runs set status = 'queued', engine_worker = null, engine_claimed_at = null,
         exec_worker = null, exec_claimed_at = null, exec_seen_at = null, releases = releases + 1
   where id = p_run and status = 'running' and engine_worker = p_worker and attempts = p_attempt
   returning submission_id into v_sub;
  if v_sub is not null then perform private.open_refresh_submission(v_sub); end if;
end $$;

-- Watchdog: a run whose engine vanished goes back to the queue (at most 3 counted attempts), but never
-- while its executor still sends heartbeats (that agent may be calling the participant's paid API).
create function public.open_requeue_stale(p_minutes int default 45)
returns int language plpgsql security definer set search_path = public, pg_temp as $$
declare n int; r record;
begin
  n := 0;
  for r in select id, submission_id, attempts - releases as counted from public.open_runs
            where status = 'running' and engine_claimed_at < clock_timestamp() - make_interval(mins => p_minutes)
              and (exec_seen_at is null or exec_seen_at < clock_timestamp() - interval '3 minutes')
            for update skip locked loop
    if r.counted >= 3 then
      update public.open_runs set status = 'failed', error = 'evaluation interrupted three times', finished_at = clock_timestamp() where id = r.id;
    else
      update public.open_runs set status = 'queued', engine_worker = null, engine_claimed_at = null,
             exec_worker = null, exec_claimed_at = null, exec_seen_at = null where id = r.id;
    end if;
    perform private.open_refresh_submission(r.submission_id);
    n := n + 1;
  end loop;
  return n;
end $$;

do $$
declare f text;
begin
  foreach f in array array['open_engine_claim(text)','open_engine_post(uuid,text,int,int,jsonb)',
      'open_engine_fetch(uuid,int,text,int)','open_finish(uuid,text,int,text,double precision,jsonb,text,jsonb)',
      'open_release(uuid,text,int)','open_requeue_stale(int)',
      'open_exec_claim(text)','open_exec_alive(uuid,text,int)','open_exec_post(uuid,text,int,text,int,jsonb)',
      'open_exec_fetch(uuid,text,int,int)'] loop
    execute format('revoke all on function public.%s from public, anon, authenticated', f);
  end loop;
  foreach f in array array['open_engine_claim(text)','open_engine_post(uuid,text,int,int,jsonb)',
      'open_engine_fetch(uuid,int,text,int)','open_finish(uuid,text,int,text,double precision,jsonb,text,jsonb)',
      'open_release(uuid,text,int)','open_requeue_stale(int)'] loop
    execute format('grant execute on function public.%s to service_role', f);
  end loop;
  foreach f in array array['open_exec_claim(text)','open_exec_alive(uuid,text,int)',
      'open_exec_post(uuid,text,int,text,int,jsonb)','open_exec_fetch(uuid,text,int,int)'] loop
    execute format('grant execute on function public.%s to open_executor', f);
  end loop;
end $$;
revoke all on function private.open_refresh_submission(uuid) from public, anon, authenticated;

-- The sealed hidden bundle (open_track/crypto.py) lives in a private bucket without policies: only the
-- service role can read it, and only the engine job holds the key that opens it.
insert into storage.buckets(id, name, public) values ('open-private', 'open-private', false) on conflict (id) do nothing;

insert into public.open_problems(id, title_zh, title_en, version, seed_indices, wallclock_seconds, kit_url, sort) values
  ('nu_followup_v5', '中微子多信使后随', 'Neutrino multi-messenger follow-up', 'v5', array[0,1,2,3,4], 600, 'open/kits/nu_followup_v5.zip', 1),
  ('cr_array_v5', '宇宙线空气簇射阵列运行', 'Cosmic-ray air-shower array operations', 'v5', array[0,1,2,3,4], 600, 'open/kits/cr_array_v5.zip', 2),
  ('sn_burst_v4', '超新星中微子爆发预警', 'Supernova neutrino burst early warning', 'v4', array[0,1,2,3,4], 600, 'open/kits/sn_burst_v4.zip', 3),
  ('osc_run_v3', '反应堆中微子振荡实验运行', 'Reactor-neutrino oscillation experiment operations', 'v3', array[0,1,2,3,4], 600, 'open/kits/osc_run_v3.zip', 4);
