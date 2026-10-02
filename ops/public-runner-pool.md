# Public-repository runner pool

GitHub-hosted runners are free and unmetered for **public** repositories. The
public pool is one public repository,
`AGENTIC-OBSERVER26-runner-12/observer-public` (repository id `1401336826`),
that takes evaluation jobs as an **overflow** of the private runner
organizations (`AGENTIC-OBSERVER26-runner-N/observer-control`). It is **off by
default**; nothing changes until an organizer switches it on.

Everything about a public run is visible to anyone: the workflow code, the run
page, its log, its inputs and any artifact. The pool is built so that none of
it carries anything private.

## What a public run can see, and what the public can see

| | Private pool | Public pool |
|---|---|---|
| Dispatch inputs (public) | `job_id`, `job_nonce` | `job_id` only (an opaque UUID) |
| Claim binding | nonce + GitHub OIDC (private repository) | the run id GitHub returned at dispatch + GitHub OIDC (`repository_visibility=public`, approved runtime tag only) |
| Claim payload (signed URLs, run credentials, manifest) | plain JSON over TLS | sealed to the job's runner key |
| Scenario bundle | signed URL to the bundle | signed URL to a **sealed copy** (`observer-staging/sealed/<job>/scenario.zip`) |
| Participant project | GitHub archive URL | signed URL to a **sealed copy** (`…/project.zip`) |
| Result | pushed to the team's private repository with a one-repository token | **sealed to the backend's public key**, uploaded to `…/result.zip` through an upload URL issued only when the result is ready; the backend opens it and commits it to the team's private repository. The runner never gets a repository token. |
| Run log | two status lines | one status line; all runtime output goes to `/dev/null` |
| Artifacts, caches, job summary | none | none (log retention 1 day) |

Sealing ("observer-seal-v1", `project_platform/sealing.py` and
`supabase/functions/_shared/observer-seal.ts`): ephemeral X25519 + HKDF-SHA256 +
AES-256-GCM. The runner generates a fresh X25519 key pair in memory for every
job and sends only the public half with its claim; the backend seals the claim
payload, the scenario and the project to it. The result is sealed to the public
half of `OBSERVER_RESULT_SEAL_KEY`, a Supabase secret that never leaves the
backend; the runner receives only the public key. Each sealed object is bound
to its purpose and job (`claim:<job>`, `scenario:<job>`, `project:<job>`,
`result:<job>`), so it cannot be replayed as another object or for another job.
A leaked signed URL yields only ciphertext. The dispatcher deletes the sealed
staging objects once the job has finished.

The participant's container keeps every sandbox and hardening layer of the
private pool (restricted egress, read-only root, the independent rescore): the
public pool runs the same trusted engine code, exported from the public
competition repository by `scripts/build-observer-control.py --public`.

Repository settings (set once, keep them): Actions limited to GitHub-owned
actions, default token read-only, fork pull request workflows need approval
for all outside contributors, log and artifact retention 1 day, issues / wiki /
projects off, no secrets, variable `OBSERVER_JOB_URL` only. There is no push or
pull request workflow in the repository.

## Which jobs use it

Only colocated engine jobs (one job per run, public scenarios of a colocated
phase; never split execute/engine runs, randomized private instances,
preparation or rescore jobs), and only for phases switched on in
`private.observer_public_pool_phases`. A **sealed (hidden) phase** such as
`final-hidden` additionally needs `sealed_transfer_verified = true`, which an
organizer sets after an end-to-end drill has shown the sealed path working.

Modes (`observer_set_public_pool`):

| mode | effect |
|---|---|
| `off` (default) | never used; queued public jobs go back to their organization |
| `drill` | only runs of `drill_users` (in enabled phases) |
| `overflow` | runs of `drill_users`, plus any enabled-phase run whose own organization is at `overflow_ratio` (default 0.8) of its monthly minutes, has `busy_jobs` (default 12) active jobs, or when every organization is over its limit; also a job whose organizations all failed to dispatch, before the self-hosted fallback |

Caps keep use modest: at most `max_active` (default 3) public jobs at once and
`monthly_minute_cap` (default 6000) minutes per month.

A public job that GitHub never starts (no claim ten minutes after dispatch), a
public dispatch that fails (it is then dispatched to its own organization in
the same round), a queued public job left for five minutes, and a queued public
job when the pool is switched off all go back to their own organization
(`observer_public_return_job`) **for good**: a returned job is never offered to
the pool again, so a broken pool cannot bounce jobs. The run's session window is
extended by the time spent in the pool. A late claim by the abandoned public
run is refused. When every private organization fails to dispatch, the public
pool is tried before the self-hosted fallback, and the fallback still follows if
the public dispatch fails.

`observer-public` shares runner-12's concurrent-job limit (GitHub Free: 20)
with runner-12's private jobs; a public job that waits more than ten minutes
for a runner goes home. Rescore jobs of public runs run in the team's own
organization.

## Switches

```sql
select public.observer_public_pool();                          -- state, minutes used, enabled phases
select public.observer_set_public_pool(p_mode=>'off');         -- turn it off (the kill switch)
select public.observer_set_public_pool(p_mode=>'overflow');    -- overflow for enabled phases
select public.observer_set_public_pool(p_mode=>'drill', p_drill_users=>array['<user uuid>']::uuid[]);
select public.observer_set_public_pool(p_max_active=>3, p_monthly_minute_cap=>6000,
  p_overflow_ratio=>0.8, p_busy_jobs=>12);
select public.observer_set_public_pool_phase('practice-projects', true);
select public.observer_set_public_pool_phase('online', true);
-- hidden final: only after a passing sealed-transfer drill
select public.observer_set_public_pool(p_sealed_transfer_verified=>true);
select public.observer_set_public_pool_phase('final-hidden', true);
```

Every change is audited (`observer.public_pool`, `observer.public_pool_phase`).
Turning the pool off never interrupts a run already claimed.

## Updating the runtime

1. `python scripts/build-observer-control.py --public <new dir>` from the
   reviewed main commit, commit it to `observer-public` `main`, tag
   `observer-runtime-<commit sha>` and push both (SSH; the HTTPS token lacks the
   workflow scope).
2. `update private.observer_installations` is not involved; approve the commit
   with `update private.observer_public_pool set approved_sha='<sha>';` while
   no public job is in flight. Only the tag is ever dispatched.

## Deployment order

1. Migration `20261002000500_public_runner_pool.sql`
   (`scripts/deploy-observer-backend.py --apply`). Pool row absent = off.
2. Supabase secret `OBSERVER_RESULT_SEAL_KEY`: 32 random bytes, unpadded
   base64url, e.g.
   `python3 -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode())"`.
   Without it (or if it is malformed) the job API refuses every public-pool
   request; the private pool is unaffected. Rotating it only affects results
   in flight.
   The GitHub App installation on runner-12 must cover `observer-public`
   (`repository_selection=all` does) with `actions: write`. No organization or
   repository variable may turn on debug logging (`ACTIONS_STEP_DEBUG`,
   `ACTIONS_RUNNER_DEBUG`): debug lines would appear on the public page.
3. Edge functions `observer-job`, then `observer-dispatch`.
4. Pool row: `insert into private.observer_public_pool(organization,repository_id,organization_id,approved_sha)
   values('AGENTIC-OBSERVER26-runner-12','1401336826','334569349','<sha>');`
5. Drill (`drill` mode, a test team, a practice card), check the public run page,
   then `overflow` with the phases to cover.

## Checking

```sql
select runner, status, count(*) from private.observer_jobs
  where created_at > now() - interval '1 day' group by 1, 2;
select id, home_organization, public_run_id, status, error from private.observer_jobs
  where runner = 'public-hosted' order by created_at desc limit 20;
```
