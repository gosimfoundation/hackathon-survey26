# Runner organizations 13–36 preparation status

Tracking issue for the 24 additional evaluation runner organizations
(`AGENTIC-OBSERVER26-runner-13` … `runner-36`). New organizations are recorded
`"enabled": false` in `ops/github-installations.json` until deliberately turned
on; runner-13 was enabled on 2026-10-01 after its approved runtime was
re-verified against runner-1…12. On 2026-10-01 all thirteen organizations
were moved to the runtime exported from main `9791047` (timed observation
requests, #111/#125), and later that day to the runtimes from main `9cf6f63`
(preparation retries, #132) and main `e7b9207` (evaluation hardening:
model-proxy-only egress and the `observer-score.yml` rescore job, #135), each
verified blob-by-blob against the export.

Each organization needs (reference: runner-1…13, runtime from main `e7b9207`):

1. GitHub organization on the Free plan, owned by BH3GEI (web UI only).
2. Private `observer-control` repository (not a fork, default branch `main`)
   containing the 56-file trusted runtime exported by
   `scripts/build-observer-control.py` from main `e7b9207`
   (byte-identical to the approved runner-1…13 inventories).
3. Installation of GitHub App `agentic-observer-2026-evaluator`
   (app_id 5057707) with `repository_selection=all`.
4. Repository variable `OBSERVER_JOB_URL` pointing at the job API.
5. Tag `observer-runtime-<approved control commit sha>` on the approved commit.
6. A recorded row in `ops/github-installations.json` with `"enabled": false`.

| Organization | Status | organization_id | installation_id | repository_id | approved_sha |
|---|---|---|---|---|---|
| AGENTIC-OBSERVER26-runner-13 | ✅ enabled in scheduling 2026-10-01 (all 6 steps done 2026-09-30; runtime republished from main `e7b9207` together with runner-1…12) | 336376701 | 166758323 | 1399205505 | fe20acc844a09f35ba08e4763aef3c759ec8d297 |
| AGENTIC-OBSERVER26-runner-14 … runner-36 | ⛔ not created | — | — | — | — |

Notes:

- Creation of runner-14+ was stopped on 2026-09-30: GitHub's anti-abuse
  verification on the organization-creation form stalled
  ("Waiting for verification", all names reported unavailable). No
  workarounds were attempted; the account must not be put at risk. Remaining
  organizations can be created manually in the web UI at a later time, then
  configured per the checklist above (`gh` + App install) and appended here.
- The `observer-control` push CI ("Trusted runtime tests") fails identically
  on every approved runner-1…13 runtime (now from `e7b9207`)
  (tests expect the starter-kit fixtures, now `archive/starter_kit_v3/`, which the trusted export intentionally
  omits). Dispatch workflows (Observer prepare/execute/engine/score) are
  unaffected.
- Database: migration `20260930000200_thirtysix_runner_organizations.sql`
  relaxes the organization-name checks to runner-1…36. It does not insert
  installations or enable anything.
