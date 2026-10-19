"""Permission check for create.gosim.org/survey26 — every read and write the website makes, run as the role that makes it, inside discarded transactions.

Each flow is one throwaway transaction. Inside it, each step runs in its own sub-block so one failure
does not hide the next; the step records 'ok', a value, or 'ERR: <message>'. Expectations are written
next to each step: `want='ok'` means the site needs this to work; `want='deny'` means it must be refused.
"""
import json, sys, uuid
import sandbox
from sandbox import pg

A, B = str(uuid.uuid4()), str(uuid.uuid4())
# Picked fresh each run, so a team leaving or an admin changing never breaks the check.
_, _admin = sandbox.raw("select id from public.profiles where is_admin and not is_banned order by created_at limit 1")
ADMIN = _admin[0]['id']
_, _real = sandbox.raw("select e.report_path, t.leader_id from public.evaluations e join public.submissions s on s.id = e.submission_id "
                       "join public.teams t on t.id = s.team_id where e.report_path is not null and t.leader_id is not null "
                       "and e.report_path <> '' order by e.created_at desc limit 1")
REAL_LEADER, REAL_REPORT = _real[0]['leader_id'], _real[0]['report_path']
# Organizer rule (2026-09-27): new teams are refused once 150 visible teams exist. When the cap is reached,
# check that refusal, then lift the cap inside the throwaway transaction so every other team action is
# still exercised. The raised value is rolled back with everything else.
_, _cap = sandbox.raw("select (public.team_capacity()->>'full')::boolean as full")
TEAMS_FULL = bool(_cap[0]['full'])
# The organizers closed the CSV practice phase on 2026-10-02 and moved practice to complete-project
# boards. While it accepts results files the full submit/cancel path is exercised; once closed, the
# check becomes "a results file is refused", and the steps that need that submission are skipped.
_, _csv = sandbox.raw("select coalesce(bool_and(public.phase_status(p) = 'open' and p.allow_results), false) as open from public.phases p where p.slug = 'practice'")
CSV_OPEN = bool(_csv[0]['open'])

def meta(name, seeking='astro'):
    # exactly what RegisterPage.vue sends as user metadata (every value a string)
    return json.dumps({"name": name, "github": "octocat", "affiliation": "Sandbox Univ", "seeking": seeking, "seeking_count": "2",
                       "locale": "zh", "astro_level": "2", "ai_level": "1", "role": "student", "city": "Shenzhen",
                       "contact": "wechat: sandbox", "heard_from": "friend", "blurb": "hello", "show_on_wall": "true"})

def mk_user(uid, email, name):
    return (f"insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at) "
            f"values ('00000000-0000-0000-0000-000000000000', {pg(uid)}, 'authenticated', 'authenticated', {pg(email)}, '', now(), "
            f"'{{\"provider\":\"email\",\"providers\":[\"email\"]}}', {pg(meta(name))}::jsonb, now(), now());")

def become(uid, role='authenticated'):
    claims = json.dumps({"sub": uid, "role": role}) if uid else json.dumps({"role": role})
    return (f"execute 'reset role'; perform set_config('request.jwt.claims', {pg(claims)}, true); "
            f"perform set_config('request.jwt.claim.sub', {pg(uid or '')}, true); execute 'set local role {role}';")

EXPECT = {}
def step(name, sql, want='ok'):
    """sql may set `tmp` (jsonb) to record a value; otherwise the step records 'ok'."""
    EXPECT[name] = want
    return (f"begin tmp := null; {sql} res := res || jsonb_build_object({pg(name)}, coalesce(tmp, '\"ok\"'::jsonb)); "
            f"exception when others then res := res || jsonb_build_object({pg(name)}, 'ERR: ' || sqlerrm); end;")

def val(expr):  # record a scalar result
    return f"select to_jsonb(({expr})) into tmp;"

# ---------------------------------------------------------------------------------------------
flows = {}

flows['participant: sign-up, profile, team, teammate, submissions, credits'] = "\n".join([
    step('sign-up creates the profile (as the auth service does)', mk_user(A, f'sandbox-a-{A[:8]}@example.test', 'Sandbox A') +
         val(f"(select jsonb_build_object('name', name, 'seeking', seeking, 'n', seeking_count, 'astro', astro_level, 'wall', show_on_wall, 'contact', contact) from public.profiles where id={pg(A)})")),
    step('second participant signs up', mk_user(B, f'sandbox-b-{B[:8]}@example.test', 'Sandbox B')),
    become(A),
    step('me()', val("public.me()->>'email'")),
    step('profile page save (all fields)', f"""update public.profiles set name='A2', github='octo', affiliation='X', role='student', locale='en',
        seeking='ai', seeking_count=1, looking_for_team=true, astro_level=1, ai_level=2, city='SZ', contact='c', blurb='b', show_on_wall=true
        where id={pg(A)}; get diagnostics n = row_count; tmp := to_jsonb(n);"""),
    step('teammates page save', f"""update public.profiles set show_on_wall=false, blurb='', contact='', seeking='', seeking_count=0, looking_for_team=false
        where id={pg(A)}; get diagnostics n = row_count; tmp := to_jsonb(n);"""),
    step('participants wall', val("(select count(*) from public.participants_wall(500))")),
    step('open teams list', val("(select count(*) from public.open_teams())")),
    *([step('create team refused at the 150-team cap', "perform public.create_team('Sandbox Team', 3, 'idea', ''); " + val("public.my_team_id()"), want='deny'),
       "execute 'reset role'; insert into public.site_settings (key, value) values ('team_limit', '100000'::jsonb) "
       "on conflict (key) do update set value = excluded.value;",
       become(A)] if TEAMS_FULL else []),
    step('create team', "perform public.create_team('Sandbox Team', 3, 'idea', ''); " + val("public.my_team_id()")),
    step('read own team row (select *)', val("(select count(*) from public.teams where id = public.my_team_id())")),
    step('team members', val("(select count(*) from public.team_members(public.my_team_id()))")),
    step('edit team', "perform public.update_team('new idea', 'https://github.com/x/y', 3, false);"),
    step('regenerate invite code', "perform public.regenerate_invite_code();"),
    step('daily submission count', val("public.team_daily_count('practice')")),
    step('upload a results file (storage insert)', "insert into storage.objects (bucket_id, name, owner, owner_id, metadata) values ('submissions', public.my_team_id()::text || '/1-abc.csv', auth.uid(), auth.uid()::text, '{}');"),
    step('create results submission' if CSV_OPEN else 'results file refused (CSV practice closed)', val("public.create_submission('practice', 'results', 'dev-reference', public.my_team_id()::text || '/1-abc.csv', 'decisions.csv', 'sha', '', '')"), want='ok' if CSV_OPEN else 'deny'),
    step('upload an agent file (storage insert)', "insert into storage.objects (bucket_id, name, owner, owner_id, metadata) values ('submissions', public.my_team_id()::text || '/2-abc.py', auth.uid(), auth.uid()::text, '{}');"),
    # Results files only since 2026-09-24: an agent package must be refused in every phase.
    step('agent package refused (results files only)', val("public.create_submission('practice', 'agent', null, public.my_team_id()::text || '/2-abc.py', 'my_strategy.py', 'sha', '', '')"), want='deny'),
    step('read own submission file back', val("(select count(*) from storage.objects where bucket_id='submissions' and name like public.my_team_id()::text || '/%')")),
    step('submissions list (select * + phase + scenario + evaluations + submitter name)', val("""(select count(*) from (
        select s.*, p.slug, p.name_en, p.name_zh, sc.slug, sc.name,
          (select json_agg(e) from public.evaluations e where e.submission_id = s.id),
          (select pr.name from public.profiles pr where pr.id = s.user_id)
        from public.submissions s left join public.phases p on p.id = s.phase_id left join public.scenarios sc on sc.id = s.scenario_id
        where s.team_id = public.my_team_id()) q)""")),
    step('queue position', val("public.queue_position((select max(id) from public.submissions where team_id = public.my_team_id()))")),
    *([step('cancel own submission', "perform public.cancel_submission((select max(id) from public.submissions where team_id = public.my_team_id()));")] if CSV_OPEN else []),
    step('credits: providers', val("(select count(*) from public.redeem_providers())")),
    step('credits: my codes', val("(select count(*) from public.my_redeem_codes())")),
    step('credits: read own code rows', val("(select count(*) from public.redeem_codes where team_id = public.my_team_id())")),
    # teammate B joins with the code, sees contact details, takes over, and A leaves
    "execute 'reset role';",
    "select to_jsonb(invite_code) into tmp from public.teams where leader_id = " + pg(A) + "; t := tmp #>> '{}';",
    become(B),
    step('join team with invite code', "perform public.join_team(t);" + val("public.my_team_id() is not null")),
    step('see teammate contact', val(f"public.teammate_contact({pg(A)}) is not null")),
    step('read teammate names (profiles select)', val(f"(select count(*) from public.profiles where team_id = public.my_team_id())")),
    become(A),
    step('transfer leadership', f"perform public.transfer_leadership({pg(B)});"),
    step('leave team', "perform public.leave_team();" + val("public.my_team_id() is null")),
    become(B),
    *([step('disband a team with submissions (refused by design)', "perform public.disband_team();", want='deny')] if CSV_OPEN else []),
])

flows['participant: things that must be refused'] = "\n".join([
    step('sign-up', mk_user(A, f'sandbox-a-{A[:8]}@example.test', 'Sandbox A')),
    become(A),
    step('make self admin', f"update public.profiles set is_admin = true where id = {pg(A)};", want='deny'),
    step('unban / edit another user', f"update public.profiles set name = 'x' where id = {pg(ADMIN)}; get diagnostics n = row_count; if n = 0 then raise exception 'no rows (refused by row rules)'; end if;", want='deny'),
    step('read another team\'s submissions', val(f"(select count(*) from public.submissions where team_id <> coalesce(public.my_team_id(), '00000000-0000-0000-0000-000000000000'))") + " if (tmp #>> '{}')::int = 0 then raise exception 'none visible'; end if;", want='deny'),
    step('read another team\'s invite codes', val("(select count(*) from (select invite_code from public.teams) q)"), want='deny'),
    step('read another team\'s report file', f"perform 1 from storage.objects where bucket_id='results' and name={pg(REAL_REPORT)}; if not found then raise exception 'hidden'; end if;", want='deny'),
    step('admin: list users', val("(select count(*) from public.admin_users(''))") + " if (tmp #>> '{}')::int = 0 then raise exception 'empty'; end if;", want='deny'),
    step('admin: ban a user', f"perform public.admin_set_user({pg(ADMIN)}, 'toggle_ban');", want='deny'),
    step('admin: rescore', "perform public.admin_rescore_phase('practice');", want='deny'),
    step('write an announcement', "insert into public.announcements (title_en, title_zh, body_en, body_zh) values ('x','x','x','x');", want='deny'),
    step('upload into another team\'s folder', "insert into storage.objects (bucket_id, name, owner, owner_id, metadata) values ('submissions', '62430aa2-57cc-4ae4-ad00-9cc42cc429a6/evil.csv', auth.uid(), auth.uid()::text, '{}');", want='deny'),
    step('submit without a team', val("public.create_submission('practice', 'results', 'dev-reference', 'x/y.csv', 'd.csv', '', '', '')"), want='deny'),
])

flows['real team member reading their own results'] = "\n".join([
    become(REAL_LEADER),
    step('read own report file', val(f"(select count(*) from storage.objects where bucket_id='results' and name={pg(REAL_REPORT)})")),
    step('read own evaluations', val("(select count(*) from public.evaluations e join public.submissions s on s.id = e.submission_id where s.team_id = public.my_team_id())")),
    step('dashboard: recent submissions', val("(select count(*) from public.submissions where team_id = public.my_team_id())")),
])

flows['visitor who is not logged in'] = "\n".join([
    become(None, 'anon'),
    step('phases with scenarios (select *)', val("(select count(*) from (select p.*, ps.scenario_id, s.id, s.slug, s.name, s.description, s.weather_public, s.forecasts_public, s.events_public, s.tiles_public, s.is_active, s.n_slots, s.n_nights, s.n_tiles, s.n_targets, s.n_requests, s.global_wallclock_seconds, s.contract, s.created_at from public.phases p left join public.phase_scenarios ps on ps.phase_id = p.id left join public.scenarios s on s.id = ps.scenario_id) q)")),
    step('announcements (select *)', val("(select count(*) from (select * from public.announcements) q)")),
    step('setting: registration_open', val("(select count(*) from public.site_settings where key='registration_open')")),
    step('setting: registration_deadline', val("(select count(*) from public.site_settings where key='registration_deadline')")),
    step('setting: mechanics_public', val("(select count(*) from public.site_settings where key='mechanics_public')")),
    step('setting: credits_note', val("(select count(*) from public.site_settings where key='credits_note')") + " if (tmp #>> '{}')::int = 0 then raise exception 'hidden'; end if;"),
    step('setting: worker_heartbeat', val("(select count(*) from public.site_settings where key='worker_heartbeat')") + " if (tmp #>> '{}')::int = 0 then raise exception 'hidden'; end if;"),
    step('setting: admin_emails stays hidden', val("(select count(*) from public.site_settings where key='admin_emails')") + " if (tmp #>> '{}')::int = 0 then raise exception 'hidden'; end if;", want='deny'),
    step('setting: excluded_accounts stays hidden', val("(select count(*) from public.site_settings where key='excluded_accounts')") + " if (tmp #>> '{}')::int = 0 then raise exception 'hidden'; end if;", want='deny'),
    step('participants wall', val("(select count(*) from public.participants_wall(500))")),
    step('participant stats', val("public.participants_stats()")),
    step('leaderboard', val("(select count(*) from public.leaderboard('practice', 500))")),
    step('champion run must stay private', "if public.champion_run() is not null then raise exception 'private run leaked'; end if;"),
    step('champion report path must stay private', "if public.champion_report_path() is not null then raise exception 'private path leaked'; end if;"),
    step('all participant results hidden from visitors', "if exists(select 1 from storage.objects where bucket_id='results') then raise exception 'private result leaked'; end if;"),
    step('public scenario files (tiles, weather, config)', val("(select count(*) from storage.objects where bucket_id='scenarios' and name like 'dev-reference/%')")),
    step('invite codes hidden from visitors', val("(select count(*) from (select invite_code from public.teams) q)"), want='deny'),
])

flows['admin console'] = "\n".join([
    become(ADMIN),
    step('stats', val("public.admin_stats() is not null")),
    step('users', val("(select count(*) from public.admin_users(''))")),
    step('teams', val("(select count(*) from public.admin_teams())")),
    step('scenarios', val("(select count(*) from public.admin_scenarios())")),
    step('redeem codes', val("(select count(*) from public.admin_redeem_codes(null, null))")),
    step('redeem stats', val("public.admin_redeem_stats() is not null")),
    step('audit log', val("(select count(*) from public.audit_log)")),
    step('scenario jobs', val("(select count(*) from public.scenario_jobs)")),
    step('all submissions with team/email/phase/scenario', val("(select count(*) from public.submissions s left join public.teams t on t.id=s.team_id left join public.profiles p on p.id=s.user_id left join public.phases ph on ph.id=s.phase_id left join public.scenarios sc on sc.id=s.scenario_id)")),
    step('post announcement', "insert into public.announcements (title_en, title_zh, body_en, body_zh) values ('t','t','b','b');"),
    step('edit announcement', "update public.announcements set title_en = 't2' where id = (select max(id) from public.announcements);"),
    step('delete announcement', "delete from public.announcements where id = (select max(id) from public.announcements);"),
    step('edit phase', "update public.phases set daily_limit = daily_limit where slug = 'practice';"),
    step('create phase', "insert into public.phases (slug, name_en, name_zh) values ('sandbox-phase', 'x', 'x');"),
    step('edit phase scenarios', "delete from public.phase_scenarios where phase_id = (select id from public.phases where slug='sandbox-phase'); insert into public.phase_scenarios (phase_id, scenario_id) select (select id from public.phases where slug='sandbox-phase'), id from public.scenarios limit 1;"),
    step('delete phase', "delete from public.phases where slug = 'sandbox-phase';"),
    step('edit scenario', "update public.scenarios set name = name, description = description, weather_public = weather_public, forecasts_public = forecasts_public, events_public = events_public, tiles_public = tiles_public, is_active = is_active, global_wallclock_seconds = global_wallclock_seconds where slug = 'dev-reference';"),
    step('save settings (upsert)', "insert into public.site_settings (key, value) values ('registration_open', 'true'::jsonb), ('mechanics_public', 'true'::jsonb) on conflict (key) do update set value = excluded.value;"),
    step('save credits note (upsert)', "insert into public.site_settings (key, value) values ('credits_note', '\"x\"'::jsonb) on conflict (key) do update set value = excluded.value;"),
    step('ban / unban user', f"perform public.admin_set_user({pg(REAL_LEADER)}, 'toggle_ban'); perform public.admin_set_user({pg(REAL_LEADER)}, 'toggle_ban');"),
    step('submission action', "perform public.admin_submission_action((select max(id) from public.submissions), 'exclude');"),
    step('download any scenario file', val("(select count(*) from storage.objects where bucket_id='scenarios')")),
    step('queue a scenario job', "perform public.admin_queue_scenario_job('dev-fortnight', null, null, null, null);"),
])

# ---------------------------------------------------------------------------------------------
fails = 0
for title, body in flows.items():
    sql_ok, out = sandbox.as_user_raw(body)
    print(f"\n### {title}")
    if not sql_ok:
        print("   BLOCK FAILED:", str(out)[:400]); fails += 1; continue
    for name, got in out.items():
        want = EXPECT.get(name, 'ok')
        err = isinstance(got, str) and got.startswith('ERR:')
        good = (not err) if want == 'ok' else err
        if not good: fails += 1
        shown = got if isinstance(got, str) else json.dumps(got, ensure_ascii=False)
        print(f"   {'PASS' if good else 'FAIL'}  {'must work ' if want=='ok' else 'must deny '} {name:62} {shown[:150]}")
print(f"\n==== {fails} problem(s) ====")
