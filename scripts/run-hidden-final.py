#!/usr/bin/env python3
"""Evaluate every team's final version once on the hidden final phase.

Run after the formal phase ('online') has ended. For each team with a
final version in that phase (its choice, else the version of its best scored
evaluation) this creates one formal evaluation in the sealed hidden phase
('final-hidden'), outside the daily limit: one run per card linked to that phase
(the v4 cards E-H). The normal dispatcher then runs it.
Results stay invisible to participants until the hidden phase's
leaderboard_mode is set to 'published'. Operating procedure: docs/hidden-final-runbook.md.

Dry run by default: prints what would be created, the run settings of the target
phase and an estimate of runner minutes and duration. --apply creates the
evaluations in one transaction (private.observer_run_hidden_final, migrations
20260927000800 and 20261001000200). A team that already has an evaluation there
on the current card set is skipped. A failed one is recreated only with
--retry-failed, and only when the platform caused the failure; a failure caused
by the team's own project (build, crash, protocol) is final unless organizers
decide otherwise and pass --retry-participant-failures. --team limits the run to
one team (slug, name or id); --before-freeze allows that single-team test before
the public phase has ended. --limit N creates at most N evaluations per call (a
canary first, then the rest with a second --apply); the dispatcher schedules
queued runs in creation order anyway, so no further batching is needed. v4 task
cards run only colocated, so the target phase needs colocated=true.

--status prints the progress of the hidden evaluations (batches, runs, runner
minutes so far). --results prints the organizer ranking: per team the score on
every card and their mean, ranked over complete evaluations of teams that are not
hidden; --csv PATH also writes it to a local file. Neither prints card contents,
and neither changes anything. After the runs, scripts/verify-v4-run.py replays any
v4 result against its bundle.

Uses the management credential from the environment (SUPABASE_PROJECT_REF,
SUPABASE_ACCESS_TOKEN), like the other organizer scripts.
"""
import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('observer_deploy', ROOT/'scripts/deploy-observer-backend.py')
deploy = importlib.util.module_from_spec(spec); spec.loader.exec_module(deploy)
q = deploy.quote

# The dispatcher is called once a minute (private.observer_tick) and schedules at
# most five runs per call (supabase/functions/_shared/observer-orchestrate.ts).
SCHEDULED_RUNS_PER_MINUTE = 5
# Runner time on top of the card's runtime: job start, project image, scoring, upload.
OVERHEAD_MINUTES = 3


def one(rows, what):
    if len(rows) != 1: raise RuntimeError(f'Expected exactly one {what}, found {len(rows)}')
    return rows[0]


def jsonish(value):
    return json.loads(value) if isinstance(value, str) else value


def plan_sql(source, target, team, apply, before_freeze, retry_failed, retry_participant=False, limit=None):
    return ('select private.observer_run_hidden_final(' + ','.join((
        q(source)+'::uuid', q(target)+'::uuid', (q(team)+'::uuid') if team else 'null',
        'true' if apply else 'false', 'true' if before_freeze else 'false', 'true' if retry_failed else 'false',
        'true' if retry_participant else 'false', str(int(limit)) if limit is not None else 'null'))
        + ') as result')


def summarize(result):
    teams = result['teams']
    lines = [f"{'APPLIED' if result['apply'] else 'DRY RUN'}: {result['source_phase']} -> {result['target_phase']}"
             f" (source ends {result['source_ends_at']}, frozen={result['frozen']})"]
    for t in teams:
        note = t['reason'] or ''
        if t['action'] == 'deferred':
            note = 'over --limit: created by a later --apply'
        elif t['action'] != 'skip' and t['model_mode'] == 'relay':
            note = ('relay model mode: model calls will fail unless a team page stays open during the run'
                    ' (rule: switch to stored mode before the online phase ends)')
        elif t['action'] != 'skip' and t['model_mode'] == 'stored' and not t['model_key_saved']:
            note = 'stored model mode without a saved key: model calls will fail'
        if t.get('failure') and t['action'] in ('created', 'would_create'):
            note = f"retry after {t['failure']} failure" + ('; ' + note if note else '')
        if t.get('stale_batches'):
            note += f"{'; ' if note else ''}{t['stale_batches']} batch(es) on an earlier card set ignored"
        lines.append(f"  {t['action']:<12} {t['team_name'][:40]:<40} version={t['revision_id']} ({t['source']})"
                     f" best={t['best_score']}{' hidden-team' if t['team_hidden'] else ''}{'  ! '+note if note else ''}")
    counts = {}
    for t in teams:
        key = t['action'] if t['action'] != 'skip' else 'skip:' + (t['reason'] or '')
        counts[key] = counts.get(key, 0) + 1
    lines.append('  totals: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())) + f"; batches created now: {result['created']}")
    return '\n'.join(lines)


def target_settings(target):
    """Batch shape and runtime of the sealed phase; v4 cards need a colocated phase."""
    row = one(deploy.query('select coalesce(c.colocated,false) as colocated, c.runtime_seconds,'
                           ' (select count(*) from public.phase_scenarios where phase_id='+q(target)+'::uuid) as scenarios'
                           ' from (select 1) x left join public.observer_phase_settings c on c.phase_id='+q(target)+'::uuid'),
              'target settings')
    line = (f"  target phase: {row['scenarios']} scenario(s) per batch, runtime_seconds={row['runtime_seconds']},"
            f" colocated={str(row['colocated']).lower()}")
    if not row['colocated']:
        line += ('\n  ! v4 task cards run only colocated: set observer_phase_settings.colocated=true first,'
                 ' or every v4 run fails with v4_requires_colocated')
    return line, row


def runner_capacity(user_ids):
    """Minutes left this month per enabled runner organization and the organization of each batch user.

    Jobs go to the organization recorded for the batch's user (observer_placement); an
    organization over its limit keeps receiving its placed users' jobs, and GitHub does
    not start jobs once its minutes are used up. Returns None if the fleet functions are missing.
    """
    rows = deploy.query("select to_regprocedure('public.observer_organizations_by_load()') is not null as present")
    if not rows or not rows[0]['present']: return None
    left = {r['organization']: max(0.0, float(r['monthly_minute_limit']) - float(r['month_minutes']))
            for r in deploy.query('select organization, monthly_minute_limit, month_minutes'
                                  ' from public.observer_organizations_by_load()')}
    placed = {}
    if user_ids:
        placed = {str(r['user_id']): r['organization'] for r in deploy.query(
            'select user_id, organization from private.observer_placements where user_id=any(array['
            + ','.join(q(u) for u in user_ids) + ']::uuid[])')}
    return {'left': left, 'placed': placed}


def estimate(users, scenarios, runtime_seconds, capacity):
    """Runner minutes and wall-clock time for new batches run by the given users (one batch each)."""
    runs = len(users) * int(scenarios or 0)
    if not runs: return '  estimate: nothing to run'
    per_run = (runtime_seconds or 0) / 60 + OVERHEAD_MINUTES
    minutes = math.ceil(runs * per_run)
    hours = (runs / SCHEDULED_RUNS_PER_MINUTE + per_run) / 60
    lines = [f'  estimate: {runs} runs, up to ~{minutes} runner minutes ({per_run:.0f} min per run at most),'
             f' about {hours:.1f} h until the last run finishes ({SCHEDULED_RUNS_PER_MINUTE} runs scheduled per minute)']
    if capacity is None: return lines[0]
    left = capacity['left']
    lines.append(f'  runner capacity: {sum(left.values()):.0f} minutes left this month on {len(left)} enabled organization(s)')
    need, unplaced = {}, 0
    for user in users:
        organization = capacity['placed'].get(str(user))
        if organization is None: unplaced += 1
        else: need[organization] = need.get(organization, 0) + int(scenarios) * per_run
    short = sorted(o for o, n in need.items() if n > left.get(o, 0.0))
    for organization in short:
        lines.append(f'  ! {organization}: needs up to ~{need[organization]:.0f} min for its placed teams,'
                     f' {left.get(organization, 0.0):.0f} left (disabled or over its limit: jobs there may not start)')
    if unplaced:
        lines.append(f'  {unplaced} batch user(s) without a placement: assigned to the least loaded organization when scheduled')
    if short or sum(left.values()) < minutes:
        lines.append('  ! not enough runner minutes: enable more runner organizations, raise monthly_minute_limit'
                     ' or move placements (scripts/rebalance-observer-placements.py) first')
    return '\n'.join(lines)


CURRENT_BATCHES = """
with cur as (
  select distinct on (b.team_id) b.* from public.observer_batches b
  where b.phase_id={target}::uuid and b.purpose='formal' and private.observer_batch_covers_phase(b.id,b.phase_id)
  order by b.team_id, b.created_at desc, b.id desc)
"""


def status(target):
    """Progress of the current hidden evaluations; no scores."""
    cte = CURRENT_BATCHES.format(target=q(target))
    batches = deploy.query(cte + 'select status, count(*) as n from cur group by status order by status')
    runs = deploy.query(cte + 'select r.status, count(*) as n from public.observer_runs r join cur on cur.id=r.batch_id'
                        ' group by r.status order by r.status')
    jobs = one(deploy.query(cte + """select count(*) filter (where j.status in ('queued','dispatched','claimed')) as active,
        coalesce(sum(extract(epoch from j.finished_at-j.claimed_at))/60,0)::float as minutes,
        coalesce(avg(extract(epoch from j.finished_at-j.claimed_at))/60,0)::float as avg_minutes,
        count(j.finished_at) as finished
      from public.observer_runs r join cur on cur.id=r.batch_id
      join private.observer_jobs j on j.run_id=r.id and j.kind='engine'"""), 'job totals')
    failures = deploy.query(cte + """select case when exists(select 1 from public.observer_runs r where r.batch_id=cur.id
          and private.observer_participant_failure(r.id)) then 'participant' else 'platform' end as failure, count(*) as n
      from cur where cur.status in ('failed','cancelled') group by 1 order by 1""")
    fmt = lambda rows: ', '.join(f"{r['status' if 'status' in r else 'failure']}={r['n']}" for r in rows) or 'none'
    # Runs still queued in a failed batch are never scheduled; count only live batches.
    waiting = one(deploy.query(cte + "select count(*) as n from public.observer_runs r join cur on cur.id=r.batch_id"
                               " where r.status='queued' and cur.status in ('queued','running')"), 'queued runs')['n']
    return '\n'.join([
        f'STATUS: batches {fmt(batches)}',
        f'  runs: {fmt(runs)}',
        f'  failed batches: {fmt(failures)} (rerun platform failures with --apply --retry-failed)',
        f"  engine jobs: {jobs['active']} active, {jobs['finished']} finished, {jobs['minutes']:.0f} runner minutes so far"
        f" (avg {jobs['avg_minutes']:.1f} min per run)",
        f'  queued runs: {waiting}, about {waiting / SCHEDULED_RUNS_PER_MINUTE:.0f} min until all are scheduled',
    ])


def results(target):
    """Organizer ranking: one row per team with its current hidden evaluation."""
    cte = CURRENT_BATCHES.format(target=q(target))
    rows = deploy.query(cte + """select t.id as team_id, t.name as team_name, t.is_hidden, cur.id as batch_id,
        cur.status, cur.score, cur.revision_id, cur.finished_at,
        case when cur.status in ('failed','cancelled') then case when exists(select 1 from public.observer_runs r
          where r.batch_id=cur.id and private.observer_participant_failure(r.id)) then 'participant' else 'platform' end end as failure,
        (select jsonb_object_agg(s.slug, jsonb_build_object('status',r.status,'score',r.score,'error',nullif(r.error,'')))
          from public.observer_runs r join public.scenarios s on s.id=r.scenario_id where r.batch_id=cur.id) as runs
      from cur join public.teams t on t.id=cur.team_id""")
    cards = sorted(r['slug'] for r in deploy.query(
        'select s.slug from public.phase_scenarios ps join public.scenarios s on s.id=ps.scenario_id'
        ' where ps.phase_id='+q(target)+'::uuid'))
    mode = one(deploy.query('select leaderboard_mode from public.phases where id='+q(target)+'::uuid'), 'phase')['leaderboard_mode']
    for r in rows:
        r['runs'] = jsonish(r['runs']) or {}
        r['score'] = None if r['score'] is None else float(r['score'])
    ranked = sorted((r for r in rows if r['status'] == 'scored' and not r['is_hidden']),
                    key=lambda r: (-r['score'], r['team_name'], str(r['team_id'])))
    rank, previous = 0, None
    for position, r in enumerate(ranked, 1):
        if r['score'] != previous: rank, previous = position, r['score']
        r['rank'] = rank  # equal scores share a rank; ties are broken by the organizers
    others = sorted((r for r in rows if 'rank' not in r), key=lambda r: (r['is_hidden'], r['status'], r['team_name']))
    return ranked + others, cards, mode


def format_results(rows, cards, mode):
    lines = [f'RESULTS (leaderboard_mode={mode}; participants see nothing until it is published)',
             '  ' + ' '.join(['rank', f"{'team':<40}", *(f'{c:>9}' for c in cards), f"{'mean':>9}", ' status'])]
    for r in rows:
        score = lambda c: r['runs'].get(c, {}).get('score')
        cell = lambda v: f'{v:9.2f}' if v is not None else f"{'-':>9}"
        note = r['status'] + (f" ({r['failure']})" if r['failure'] else '') + (' hidden-team' if r['is_hidden'] else '')
        lines.append(f"  {str(r.get('rank', '-')):>4} {r['team_name'][:40]:<40} "
                     + ' '.join(cell(score(c)) for c in cards) + f" {cell(r['score'])}  {note}")
    ranked = sum(1 for r in rows if 'rank' in r)
    lines.append(f'  ranked={ranked}, not ranked={len(rows) - ranked} (incomplete, failed or hidden teams)')
    return '\n'.join(lines)


def write_csv(path, rows, cards):
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        out = csv.writer(handle)
        out.writerow(['rank', 'team_id', 'team_name', 'hidden_team', 'revision_id', 'batch_id', 'status', 'failure',
                      *cards, 'mean'])
        for r in rows:
            out.writerow([r.get('rank', ''), r['team_id'], r['team_name'], r['is_hidden'], r['revision_id'], r['batch_id'],
                          r['status'], r['failure'] or '', *(r['runs'].get(c, {}).get('score', '') for c in cards),
                          '' if r['score'] is None else r['score']])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', default='online', help='Formal phase slug (default: online)')
    parser.add_argument('--target', default='final-hidden', help='Sealed hidden phase slug (default: final-hidden)')
    parser.add_argument('--team', help='Only this team (slug, name or id)')
    parser.add_argument('--apply', action='store_true', help='Create the evaluations (default: dry run)')
    parser.add_argument('--before-freeze', action='store_true', help='With --team: allow before the source phase ends')
    parser.add_argument('--retry-failed', action='store_true',
                        help='Create a new evaluation where the previous one failed because of the platform')
    parser.add_argument('--retry-participant-failures', action='store_true',
                        help="Also recreate evaluations that failed because of the team's project (organizer decision)")
    parser.add_argument('--limit', type=int, help='With --apply: create at most this many evaluations now')
    parser.add_argument('--status', action='store_true', help='Show the progress of the hidden evaluations')
    parser.add_argument('--results', action='store_true', help='Show the organizer ranking (changes nothing)')
    parser.add_argument('--csv', help='With --results: also write the ranking to this local CSV file')
    parser.add_argument('--json', action='store_true', help='Print the full JSON result')
    args = parser.parse_args()
    if args.before_freeze and not args.team: parser.error('--before-freeze requires --team')
    if args.csv and not args.results: parser.error('--csv requires --results')
    if args.limit is not None and (not args.apply or args.limit < 1): parser.error('--limit requires --apply and a positive number')
    if (args.status or args.results) and (args.apply or args.team or args.retry_failed or args.retry_participant_failures):
        parser.error('--status and --results only read; run them without --apply, --team or --retry-*')
    target = one(deploy.query('select id from public.phases where slug='+q(args.target)), 'target phase')['id']
    if args.status or args.results:
        if args.status: print(status(target))
        if args.results:
            rows, cards, mode = results(target)
            print(json.dumps(rows, ensure_ascii=False, indent=1, default=str) if args.json else format_results(rows, cards, mode))
            if args.csv: write_csv(args.csv, rows, cards); print(f'  written to {args.csv} (keep it private until publication)')
        return
    phase = one(deploy.query('select id, ends_at is not null and now()>=ends_at as finished, ends_at from public.phases'
                             ' where slug='+q(args.source)), 'source phase')
    source = phase['id']
    if not phase['finished'] and not args.before_freeze:
        # The database refuses this (source_phase_not_finished); say why instead of an opaque API error.
        parser.error(f"{args.source} has not ended yet (ends_at={phase['ends_at']}); test one team with --team ... --before-freeze")
    team = None
    if args.team:
        team = one(deploy.query('select id from public.teams where id::text='+q(args.team)+' or slug='+q(args.team)
                                +' or name='+q(args.team)), 'team')['id']
    result = jsonish(one(deploy.query(plan_sql(source, target, team, args.apply, args.before_freeze, args.retry_failed,
                                               args.retry_participant_failures, args.limit)), 'result')['result'])
    if args.json: print(json.dumps(result, ensure_ascii=False, indent=1)); return
    line, settings = target_settings(target)
    users = [t['user_id'] for t in result['teams'] if t['action'] in ('would_create', 'created')]
    print(summarize(result) + '\n' + line + '\n'
          + estimate(users, settings['scenarios'], settings['runtime_seconds'], runner_capacity(users)))


if __name__ == '__main__': main()
