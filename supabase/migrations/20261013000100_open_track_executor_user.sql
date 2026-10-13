-- Open track: let the executor also authenticate as a dedicated Supabase Auth user.
-- The project signs JWTs with an asymmetric key (ES256) whose private half cannot be exported, so a
-- role=open_executor token cannot be minted. The executor therefore signs in as one ordinary auth user
-- listed in private.open_executor_users; the four executor functions accept that user (or a
-- role=open_executor JWT) and reject everyone else. The user has no other powers: as a plain
-- "authenticated" caller it still cannot read organizer tables, call engine functions or write scores.
-- Additive only: one new table, one guard function, the four executor functions redefined with the guard.

create table private.open_executor_users (
  user_id uuid primary key,
  note text not null default '',
  created_at timestamptz not null default now()
);
revoke all on private.open_executor_users from public, anon, authenticated;

create function private.open_require_executor()
returns void language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  if coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') = 'open_executor' then
    return;
  end if;
  if auth.uid() is not null and exists (select 1 from private.open_executor_users where user_id = auth.uid()) then
    return;
  end if;
  raise exception 'not_executor';
end $$;
revoke all on function private.open_require_executor() from public, anon, authenticated;

create or replace function public.open_exec_claim(p_worker text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare r public.open_runs; s public.open_submissions; f private.open_submission_files;
begin
  perform private.open_require_executor();
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

create or replace function public.open_exec_alive(p_run uuid, p_worker text, p_attempt int)
returns boolean language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform private.open_require_executor();
  update public.open_runs set exec_seen_at = clock_timestamp()
   where id = p_run and status = 'running' and exec_worker = p_worker and attempts = p_attempt;
  return found;
end $$;

create or replace function public.open_exec_post(p_run uuid, p_worker text, p_attempt int, p_direction text, p_seq int, p_body jsonb)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  perform private.open_require_executor();
  if p_direction not in ('from_agent', 'usage') then raise exception 'invalid_direction'; end if;
  if not exists (select 1 from public.open_runs where id = p_run and status = 'running'
                 and exec_worker = p_worker and attempts = p_attempt) then raise exception 'run_not_owned'; end if;
  if octet_length(p_body::text) > 1048576 then raise exception 'message_too_large'; end if;
  insert into private.open_messages(run_id, attempt, direction, seq, body) values (p_run, p_attempt, p_direction, p_seq, p_body)
    on conflict do nothing;
end $$;

create or replace function public.open_exec_fetch(p_run uuid, p_worker text, p_attempt int, p_after int)
returns table (seq int, body jsonb) language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  perform private.open_require_executor();
  return query
  select m.seq, m.body from private.open_messages m
   where m.run_id = p_run and m.attempt = p_attempt and m.direction = 'to_agent' and m.seq > p_after
     and exists (select 1 from public.open_runs r where r.id = p_run and r.exec_worker = p_worker and r.attempts = p_attempt)
   order by m.seq limit 200;
end $$;

do $$
declare f text;
begin
  foreach f in array array['open_exec_claim(text)','open_exec_alive(uuid,text,int)',
      'open_exec_post(uuid,text,int,text,int,jsonb)','open_exec_fetch(uuid,text,int,int)'] loop
    execute format('revoke all on function public.%s from public, anon', f);
    execute format('grant execute on function public.%s to open_executor, authenticated', f);
  end loop;
end $$;
