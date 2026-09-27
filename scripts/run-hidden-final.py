#!/usr/bin/env python3
"""Evaluate every team's final version once on the hidden final phase.

Run after the formal phase ('online') has ended. For each team with a
final version in that phase (its choice, else the version of its best scored
evaluation) this creates one formal evaluation in the sealed hidden phase
('final-hidden'), outside the daily limit. The normal dispatcher then runs it.
Results stay invisible to participants until the hidden phase's
leaderboard_mode is set to 'published'.

Dry run by default: prints what would be created. --apply creates the
evaluations in one transaction (private.observer_run_hidden_final, migration
20260927000800). Teams that already have an evaluation there are skipped; a
failed one is retried only with --retry-failed. --team limits the run to one
team (slug, name or id); --before-freeze allows that single-team test before the
public phase has ended. Uses the management credential from the environment
(SUPABASE_PROJECT_REF, SUPABASE_ACCESS_TOKEN), like the other organizer scripts.
"""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('observer_deploy', ROOT/'scripts/deploy-observer-backend.py')
deploy = importlib.util.module_from_spec(spec); spec.loader.exec_module(deploy)
q = deploy.quote


def one(rows, what):
    if len(rows) != 1: raise RuntimeError(f'Expected exactly one {what}, found {len(rows)}')
    return rows[0]


def plan_sql(source, target, team, apply, before_freeze, retry_failed):
    return ('select private.observer_run_hidden_final(' + ','.join((
        q(source)+'::uuid', q(target)+'::uuid', (q(team)+'::uuid') if team else 'null',
        'true' if apply else 'false', 'true' if before_freeze else 'false', 'true' if retry_failed else 'false'))
        + ') as result')


def summarize(result):
    teams = result['teams']
    lines = [f"{'APPLIED' if result['apply'] else 'DRY RUN'}: {result['source_phase']} -> {result['target_phase']}"
             f" (source ends {result['source_ends_at']}, frozen={result['frozen']})"]
    for t in teams:
        note = t['reason'] or ''
        if t['action'] != 'skip' and t['model_mode'] == 'relay':
            note = ('relay model mode: model calls will fail unless a team page stays open during the run'
                    ' (rule: switch to stored mode before the online phase ends)')
        elif t['action'] != 'skip' and t['model_mode'] == 'stored' and not t['model_key_saved']:
            note = 'stored model mode without a saved key: model calls will fail'
        lines.append(f"  {t['action']:<12} {t['team_name'][:40]:<40} version={t['revision_id']} ({t['source']})"
                     f" best={t['best_score']}{' hidden-team' if t['team_hidden'] else ''}{'  ! '+note if note else ''}")
    counts = {}
    for t in teams: counts[t['action']] = counts.get(t['action'], 0) + 1
    lines.append('  totals: ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())) + f", created={result['created']}")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', default='online', help='Formal phase slug (default: online)')
    parser.add_argument('--target', default='final-hidden', help='Sealed hidden phase slug (default: final-hidden)')
    parser.add_argument('--team', help='Only this team (slug, name or id)')
    parser.add_argument('--apply', action='store_true', help='Create the evaluations (default: dry run)')
    parser.add_argument('--before-freeze', action='store_true', help='With --team: allow before the source phase ends')
    parser.add_argument('--retry-failed', action='store_true', help='Create a new evaluation where the previous one failed')
    parser.add_argument('--json', action='store_true', help='Print the full JSON result')
    args = parser.parse_args()
    if args.before_freeze and not args.team: parser.error('--before-freeze requires --team')
    source = one(deploy.query('select id from public.phases where slug='+q(args.source)), 'source phase')['id']
    target = one(deploy.query('select id from public.phases where slug='+q(args.target)), 'target phase')['id']
    team = None
    if args.team:
        team = one(deploy.query('select id from public.teams where id::text='+q(args.team)+' or slug='+q(args.team)
                                +' or name='+q(args.team)), 'team')['id']
    result = one(deploy.query(plan_sql(source, target, team, args.apply, args.before_freeze, args.retry_failed)), 'result')['result']
    if isinstance(result, str): result = json.loads(result)
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else summarize(result))


if __name__ == '__main__': main()
