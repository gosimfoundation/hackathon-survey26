-- Award material: the hackathon requires the top six teams to open-source their code,
-- so every team needs a place to submit the repository URL. This is a dedicated column,
-- deliberately separate from teams.github_repo (the legacy scoring field), which is left
-- untouched.

alter table public.teams add column if not exists opensource_repo text not null default '';

comment on column public.teams.opensource_repo is
  '获奖材料：开源仓库地址（形如 https://github.com/组织/仓库），空字符串表示未提交。';

-- Any team member (not just the leader) may set it: collecting award material should not
-- be blocked on the captain. An empty string clears the value; anything else must look
-- like an http(s) URL with a host and a path (loose check, e.g. GitHub org/repo), at
-- most 255 characters. Membership check mirrors leave_team(), not update_team().
create or replace function public.set_opensource_repo(p_url text)
returns void language plpgsql security definer set search_path = public as $$
declare v_uid uuid := auth.uid(); v_team public.teams; v_url text;
begin
  if v_uid is null then raise exception 'not_authenticated'; end if;
  perform private.assert_not_banned();
  select t.* into v_team from public.teams t join public.profiles p on p.team_id = t.id where p.id = v_uid for update of t;
  if not found then raise exception 'not_in_team'; end if;
  v_url := left(trim(coalesce(p_url, '')), 255);
  if v_url <> '' and v_url !~ '^https?://[^/[:space:]]+/[^[:space:]]+$' then raise exception 'invalid_repo_url'; end if;
  update public.teams set opensource_repo = v_url where id = v_team.id;
end $$;

revoke all on function public.set_opensource_repo(text) from public, anon;
grant execute on function public.set_opensource_repo(text) to authenticated;

-- Surface the new field through me() so the team page can display it (unchanged otherwise).
create or replace function public.me()
returns jsonb language sql stable security definer set search_path = public as $$
  select case when auth.uid() is null then null else (
    select jsonb_build_object(
      'id', p.id, 'email', p.email, 'name', p.name, 'nickname', p.nickname, 'github', p.github, 'affiliation', p.affiliation, 'role', p.role,
      'looking_for_team', p.looking_for_team, 'seeking', p.seeking, 'seeking_count', p.seeking_count,
      'locale', p.locale, 'is_admin', p.is_admin, 'is_banned', p.is_banned,
      'astro_level', p.astro_level, 'ai_level', p.ai_level, 'city', p.city, 'contact', p.contact,
      'heard_from', p.heard_from, 'blurb', p.blurb, 'show_on_wall', p.show_on_wall, 'avatar_url', p.avatar_url,
      'uid', (select u.uid from private.profile_uids u where u.profile_id = p.id),
      'team', case when t.id is null then null else jsonb_build_object(
        'id', t.id, 'name', t.name, 'slug', t.slug, 'leader_id', t.leader_id, 'invite_code', t.invite_code,
        'project_idea', t.project_idea, 'github_repo', t.github_repo, 'opensource_repo', t.opensource_repo,
        'max_size', t.max_size, 'is_locked', t.is_locked,
        'member_count', (select count(*) from public.profiles m where m.team_id = t.id)) end)
    from public.profiles p left join public.teams t on t.id = p.team_id where p.id = auth.uid()) end;
$$;

notify pgrst, 'reload schema';
