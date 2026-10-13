-- Organizer test submissions stay in the database but are kept off the public open-track board.
-- Append-only: one new column (default false, so every existing submission keeps showing) and the
-- board function re-created with one extra filter. Participants cannot set it (they only insert
-- through open_submit, which never writes this column).
alter table public.open_submissions add column hidden boolean not null default false;

create or replace function public.open_leaderboard()
returns table (problem_id text, player text, best_total double precision, uses_model boolean,
               submissions bigint, achieved_at timestamptz)
language sql stable security definer set search_path = public, pg_temp as $$
  with scored as (
    select r.submission_id, r.problem_id, s.user_id, s.uses_model, avg(r.total) as mean_total,
           max(r.finished_at) as finished_at
      from public.open_runs r join public.open_submissions s on s.id = r.submission_id
     where s.status <> 'cancelled' and not s.hidden
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
