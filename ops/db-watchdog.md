# DB watchdog

`.github/workflows/db-watchdog.yml` + `scripts/db_watchdog.py` keep the Supabase
project (`vdiemcofukuxglqsmlyz`) up without any human in the loop. It sends no
notifications anywhere - the only trace of its activity is the Actions run log.

## What it does

Every ~5 minutes (`cron: */5 * * * *`), one workflow run:

1. Checks the project up to 4 times, ~60s apart:
   - Management API `GET /v1/projects/<ref>/health?services=db,rest,auth,storage`
   - A real end-user path: anon REST `GET` on the public `announcements` table
2. If 3 checks in a row fail, it restarts the project
   (`POST /v1/projects/<ref>/restart`), unless:
   - the project status is already `RESTARTING` or `COMING_UP`,
   - the last restart was less than 20 minutes ago, or
   - there have already been 4+ restarts in the last 6 hours.
3. Restart history (last restart time, timestamps in the last 6h) is persisted
   as `state.json` on a dedicated `db-watchdog-state` branch - never on `main`,
   and only written when a restart actually happens (dry-run or real).

A `concurrency` group (`db-watchdog`) guarantees runs never overlap: if a run
is still going when the next cron fires, the new one waits.

## Secrets

Repo Actions secrets (set via `gh secret set`): `SUPABASE_ACCESS_TOKEN`,
`SUPABASE_PROJECT_REF`, `SUPABASE_ANON_KEY`. The workflow also uses the
automatic `GITHUB_TOKEN` (needs `permissions: contents: write`) to read/write
`state.json` on the state branch via the Contents API.

## Manual testing

`workflow_dispatch` takes two inputs:
- `dry_run` - logs the restart decision but never calls the restart API
- `simulate_fail` - forces every check to report failure, so you don't have
  to wait for a real outage to exercise the restart branch

Run with both `true` to confirm the "would restart" log line without ever
touching the project. Run with just `dry_run: true` to see real health
checks end-to-end without risking an actual restart.

## Stopping it

Disable the workflow (`gh workflow disable db-watchdog.yml -R
gosimfoundation/hackathon-survey26`) or delete `.github/workflows/db-watchdog.yml`.
There is nothing else to stop - it only runs as a GitHub-hosted Action.

## Caveat

GitHub's `schedule` trigger is best-effort: under platform load, scheduled
runs can be delayed by several minutes or occasionally skipped entirely.
This watchdog is a safety net, not a guaranteed-latency SLA.
