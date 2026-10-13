# Open track (four new AOH tasks)

Individuals submit a ZIP (`agent.py` at the root, standard library only) for any subset of the active
tasks; each chosen task runs once on its fixed hidden seeds (`public.open_problems.seed_indices`) and
scores the mean. Website page: `/open`. Database: `supabase/migrations/20261013000000_open_track.sql`.

| Side | Code | Holds | Never holds |
|---|---|---|---|
| engine (trusted) | `engine.py` | service key, `OPEN_TRACK_BUNDLE_KEY` (opens the sealed hidden bundle in storage `open-private`) | participant code |
| executor | `executor.py`, `model_proxy.py` | anon key + `OPEN_EXECUTOR_TOKEN` (role `open_executor`), `OPEN_TRACK_KEY_PRIVATE` | service key, hidden seeds or wording pools |

They exchange only protocol messages (`private.open_messages`), every write bound to the worker and
attempt that claimed the run. The agent runs in a container with no network except an internal one
shared with the metered model proxy (participant's own key, allow-listed providers only).

Tools (`python -m open_track.crypto ...`): `keygen DIR` (executor key pair; put `public.jwk.json` into
`web/src/lib/executorKey.json`), `bundle SRC_ROOT OUT` (seal `_hidden/`), `executor-token [DAYS]`.
`problems/` is the public kit code (same as the downloadable kits in `web/public/open/kits/`).

Tests: `tests/supabase/test_open_track_db.py`, `tests/test_open_track_units.py` (Docker isolation when
Docker is available), `tests/supabase/test_open_track_e2e.py` (needs the hidden bundle inputs, see its
docstring), `web/tests/openTrack.test.ts`. Rollout steps: see the deployment checklist kept with the
organizer notes (OPEN_TRACK_READY.md).
