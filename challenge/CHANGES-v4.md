# v4 modules: deviations from the author's prototype

Source: `mynamesnoname/agent-observer-0927` at `3bdc2e0` (2026-09-28). Vendored files:
`v4_catalog_generator.py`, `v4_weather_simulator.py`, `v4_fiber_map.py`, `v4_scorer.py`,
`v4_runner.py`, `v4_probe_agent.py`, `v4_sky_map.py`. The author's sample configs are in
`reference/v4/`. The author's tests are in `tests/test_v4_*.py`. This file lists every change.

## Layout
- The modules stay at the top level of `challenge/`, as in the prototype. Two reasons: the
  prototype uses relative imports from `challenge.contracts` and friends, and
  `scripts/build-observer-control.py` exports only `challenge/*.py` to the runner control repos.
- `v4_output_digest.py` is not vendored. It is an organizer review tool that prints truth.
- Configs: `config/v4_*.json` became `challenge/reference/v4/v4_*.json`. Product paths are
  relative to that directory (`products/...`) instead of `../../_0927output/...`, the
  directory layout a card bundle will use. `products/` is git-ignored and never committed.
- Tests: `tests/test_v4_*.py` became `challenge/tests/test_v4_*.py`. The runner tests get
  their scenario products from a session fixture (`v4_reference_dir` in `conftest.py`) that
  generates them into a temp directory in about 5 s. The prototype needed them pre-generated
  on disk. The matplotlib demo test is skipped when matplotlib is missing (it is a
  build-time-only dependency).

## Behaviour changes
1. **Hashed per-stream seeds (R2).** Every RNG stream in the catalogue and weather generators
   now goes through `contracts.stream_seed`, which is the same code as the v3 simulators
   (PR #71). Stream names: `v4.catalog`, `v4.weather.slots`, `v4.weather.events`,
   `v4.rocket_launch`, `v4.earthquake`, `v4.terrain`, `v4.instrument_fault`,
   `v4.stress.data_loss`, `v4.stress.pointing_offset`.
   - The hashing is opt-in with `"seed_derivation": "sha256-v1"`. Without that key the
     legacy `seed + offset` streams are used, so the author's reference artifacts and anchors
     are unchanged.
   - Competition cards must opt in: `v4_config_check.cross_validate_generator_configs(...,
     require_hashed_seeds=True)`.
   - `seed` must be a non-negative integer. 128-bit secrets are fine.
2. **Seeds removed from the outputs.**
   - `summary.json` (catalogue) no longer contains `seed` or `sha256.config`. A config hash
     would let someone brute-force a small seed, and this summary may be published with the
     public inputs.
   - `v4_weather_summary.json` no longer contains `seed`. This file is truth and is never
     published.
   - `score_report.json` no longer contains `pointing_offset_deg` (hidden stress truth).
     `run_scenario` still returns it in memory under `organizer_only`.
3. **Forecast horizon clip (R6).**
   - A forecast notice's `nights` list only names nights whose observing window overlaps
     that forecast's coverage window.
   - A notice left with no nights is dropped.
   - Before this change, a long event revealed nights beyond the horizon.
4. **Config cross-validation (R7).** New module `v4_config_check.py`:
   - `cross_validate_generator_configs(catalog, weather, scenario, fiber)` checks that the
     site, survey dates, twilight limit, altitude limit and stress switch agree, and
     optionally that hashed seeds are used.
   - `validate_scenario` runs in `v4_runner.load_scenario`. It checks that the scenario and
     fibre-config sites agree, and it checks the fibre, exposure and score parameters, the
     catalogue (unique ids, ranges), slot order and overlap, event sectors, bulletin and
     forecast order, and the stress table.
5. **Invalid agent actions no longer crash the run (R4).** New `v4_runner.normalize_action`
   validates every action.
   - It rejects unknown actions and extra keys, non-finite or non-integral numbers, bad
     pointing, fibres outside 0..15 or repeated (`"5"`/`"05"`), duplicate or unknown target
     ids, programs other than DARK/BRIGHT/BACKUP, and wait durations outside [60, 3600].
   - An invalid action ends the run with termination reason `agent_error`. The score is
     settled on the valid history, as in v3.
   - Going over 32 consecutive `report` actions also ends as `agent_error` instead of raising.
   - `program` stays optional and defaults to `BACKUP`, as in the prototype.
6. **Termination reasons.**
   - `score_report.json` has a new field, `termination: {reason, detail}`. The reason is one
     of `survey_complete`, `agent_finished`, `agent_error` or `global_wallclock_expired`.
   - An agent returns `None` or `{"action": "finish"}` to finish.
   - An agent callable, or the factory (for example the platform transport adapter), raises
     `v4_runner.AgentTermination(reason, detail)` to stop the run. The run still settles.
7. **`wait` with `until_utc` (R5, protocol section 2.3).**
   - `{"action": "wait", "until_utc": "...Z"}` must be later than now.
   - The runner expands it into successive waits of at most 3600 s with no agent round trip.
     Each chunk is a `wait` row in `decisions.csv`.
   - The expansion ends early at survey end.
   - Everything published during the wait (bulletins, forecasts, a `state_resync`) is
     delivered in the next request's `new_messages`.
8. **Performance (R11).** `WeatherTruth` builds its slot-start list once, instead of on every
   `_slot_index` call. The results are unchanged.

The prototype's regression anchors are unchanged (see the PR for the reproduced totals).
