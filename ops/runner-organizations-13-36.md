# Runner organizations 13–36 preparation status

Tracking issue for the 24 additional evaluation runner organizations
(`AGENTIC-OBSERVER26-runner-13` … `runner-36`). New organizations are **not**
wired into scheduling: placement still only picks `enabled` rows of
`private.observer_installations`, and every new organization stays
`"enabled": false` in `ops/github-installations.json` until it is verified
with `scripts/configure-observer-runners.py` and deliberately turned on.

Each organization needs (reference: runner-1…12, runtime from main `472f79e`):

1. GitHub organization on the Free plan, owned by BH3GEI (web UI only).
2. Private `observer-control` repository (not a fork, default branch `main`)
   containing the 53-file trusted runtime exported by
   `scripts/build-observer-control.py` from main `472f79e`
   (byte-identical to the approved runner-1…12 inventories).
3. Installation of GitHub App `agentic-observer-2026-evaluator`
   (app_id 5057707) with `repository_selection=all`.
4. Repository variable `OBSERVER_JOB_URL` pointing at the job API.
5. Tag `observer-runtime-<main sha>` on the approved commit.
6. A recorded row in `ops/github-installations.json` with `"enabled": false`.

| Organization | Status | organization_id | installation_id | repository_id | approved_sha |
|---|---|---|---|---|---|
| AGENTIC-OBSERVER26-runner-13 | ✅ ready (all 6 steps done 2026-09-30; recorded `enabled: false`) | 336376701 | 166758323 | 1399205505 | 2a1d3694f2e3eca623e4ee298185a268b0dc0b4c |
| AGENTIC-OBSERVER26-runner-14 … runner-36 | ⛔ not created | — | — | — | — |

Notes:

- Creation of runner-14+ was stopped on 2026-09-30: GitHub's anti-abuse
  verification on the organization-creation form stalled
  ("Waiting for verification", all names reported unavailable). No
  workarounds were attempted; the account must not be put at risk. Remaining
  organizations can be created manually in the web UI at a later time, then
  configured per the checklist above (`gh` + App install) and appended here.
- The `observer-control` push CI ("Trusted runtime tests") fails identically
  on runner-13 and on the approved runner-1…12 runtimes from `472f79e`
  (tests expect `starter_kit/`, which the trusted export intentionally
  omits). Dispatch workflows (Observer prepare/execute/engine) are
  unaffected; this matches the state of the existing twelve organizations.
- Database: migration `20260930000200_thirtysix_runner_organizations.sql`
  relaxes the organization-name checks to runner-1…36. It does not insert
  installations or enable anything.
