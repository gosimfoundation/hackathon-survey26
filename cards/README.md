# v4 competition task cards: v4-a, v4-b, v4-c, v4-d

**Status: trial / work in progress.** This directory is the record of the first
attempt at building the four formal v4 task cards. It is committed so the card
parameters, the generator wiring and the smoke evidence are reviewable and
reproducible. It is **not** a finished registration: nothing here is on the
platform yet, and the cards cannot be used as formal competition material before
the items in "Before these can be formal cards" below are done.

## Naming

The canonical slug of each card is `v4-a`, `v4-b`, `v4-c`, `v4-d`. That slug is

- the `public.scenarios.slug` that `scripts/configure-v4-phases.py` matches, so the
  switch is `--formal v4-a,v4-b,v4-c,v4-d`; and
- the `task_card.scenario_slug` inside each card.

`task_card.card_id` (`A`/`B`/`C`/`D`) stays a short participant-visible label and is
independent of the slug.

## Layout

```
cards/
  build_ABCD_cards.py      the trial builder (reads spec/, writes card/ and smoke/)
  v4-a/
    spec/                  generator inputs: card.json + the four v4_*.json configs
    card/                  the built card bundle: config/ public/ truth/
    smoke/                 smoke-run evidence (decisions.csv, score_report.json, ...)
    sky_map.json           sky-map render config
    sky_map.png, .pdf      rendered footprint + target catalogue
  v4-b/ ... v4-c/ ... v4-d/    same
```

`card/` is a valid v4 card root: `V4Workflow(cards/<slug>/card)` loads it and
`is_v4_bundle()` is true. `truth/` is what only the trusted engine may read;
`public/` is what participants receive.

## Card parameters

| | v4-a | v4-b | v4-c | v4-d |
|---|---|---|---|---|
| site | VISTA/Paranal -24.62 deg | Cape Town -33.92 deg | Mauna Kea +19.82 deg | Nemo (fictional) -45 deg |
| footprint | 3 components / 6000 deg2 | 2 / 8000 deg2 | 4 / 4000 deg2 | 3 / 6000 deg2 |
| targets (required) | 30000 (1500) | 50000 (2500) | 30000 (1500) | 30000 (1500) |
| season | 2026-10-01 -> 2027-02-01 | 2027-06-01 -> 2027-12-01 | 2026-12-01 -> 2027-04-01 | 2027-01-01 -> 2028-01-01 |
| nights / slots | 123 / 3777 | 183 / 6745 | 121 / 4743 | 365 / 11536 |
| weather events | 11 (no rain/cloud/smog) | 101 | 46 | 95 |
| fibres / area | 16 (4x4) / 0.4 deg2 | 25 (5x5) / 0.064 deg2 | 9 (3x3) / 0.7 deg2 | 100 (10x10) / 0.06 deg2 |
| f0 / T0 | 0.5 / 900 | 0.8 / 1000 | 0.5 / 900 | 0.5 / 900 |
| stress | no | no | no | yes (data_loss + pointing_offset) |
| observation requests | 6 x (8 targets, min 6, reward 100) | same | same | same |
| initialize payload | 1.81 MiB | 3.01 MiB | 1.78 MiB | 1.85 MiB |

Only v4-b differs in the score config (f0/T0). `program` multipliers, `uniformity.weight`,
`required`, `reporting`, `background_closure` and `publication` are identical across all four.

v4-b is the largest card: its 3.01 MiB initialize is 2.4% of the 128 MiB
initialization limit (`project_platform/transport.py`), and because v4 is
colocated-only it never passes through the 1 MiB gzip envelope of the session API.
Its per-step snapshots carry no target catalogue (the agent computes geometry
itself), so the target count does not affect the step size.

## What is done and what is not

Done:

- spec -> bundle -> smoke pipeline, with `cross_validate_generator_configs(..., require_hashed_seeds=True)`;
- all four bundles load in place through `challenge.v4_workflow.V4Workflow`;
- sky maps render from `sky_map.json`.

Not done:

- **not registered on the platform** - no `public.scenarios` row, no files in the
  `scenarios` bucket, no private evaluation bundle in `observer-scenarios`, no
  `private.observer_scenario_bundles` row;
- the smoke run is **pipeline-level only**: 12 observes inside a 120 s wall clock,
  then `agent_finished`. `required_missing` is ~1495/1500, so the totals (about -75000)
  are meaningless as scores. `observation_requests_issued` is **0** on all four cards
  (requests start after the first night, which the probe never reaches) and v4-d's
  `data_loss` event never triggers (`invalidated_observations = 0`, no `state_resync`);
- no full-season baseline run and no score distribution exist yet;
- **no tool registers a v4 card**: `worker/main.py` is v3-only (`config/` +
  `outputs/reference/`, `scenario_builder.describe_scenario`), and
  `scripts/configure-observer-competition.py --prepare` hardcodes the v3 layout and
  `--scenarios 3`.

## Before these can be formal cards

1. **Rotate the seeds.** The specs carry trial seeds (`20261001`, `20260930`,
   `20261201`, `20270101`), and v4-a's seed is byte-identical to the seed committed in
   `challenge/reference/v4/v4_catalog_config.json`. Anyone with this public repository
   can therefore rebuild these cards' hidden weather. Formal cards need 128-bit secrets
   injected from outside git, with the `seed` field removed from `spec/`.
2. **This repository is public.** `truth/` - weather truth, events and the *future*
   observation-request stream - is committed here as part of the trial record. It is the
   answer key. Decide deliberately whether to keep it in public history, or to strip
   `truth/` (and the seeds) before pushing.
3. **Register**, per card: a `public.scenarios` row (contract `v4-score-v1`,
   `global_wallclock_seconds` 900, `weather_public`/`forecasts_public`/`events_public` all
   false); only `config/` and `public/` uploaded to `scenarios/<slug>/` (the phase switch
   refuses a formal card that has files outside those two directories); the full
   `config/`+`public/`+`truth/` bundle zipped to `observer-scenarios/<scenario_id>/<digest>.zip`
   with a `private.observer_scenario_bundles` row; then
   `scripts/configure-v4-phases.py --formal v4-a,v4-b,v4-c,v4-d --apply`.
4. **Do not use the admin "rotate seed" action on a v4 card.** It runs
   `worker/main.py:process_scenario_job`, which is v3-only and has no contract guard: it
   would overwrite `scenarios/<slug>/` with a v3 scenario and flip the row's contract,
   while the private v4 bundle stays untouched.

## Rebuilding

```bash
# from the repository root; card/ and smoke/ must be removed first (the builder refuses to overwrite)
conda run -n survey-agent python cards/build_ABCD_cards.py            # all four
conda run -n survey-agent python cards/build_ABCD_cards.py v4-a       # one card
python3 challenge/v4_sky_map.py --config cards/v4-a/sky_map.json      # needs matplotlib
```

The builder needs the vendored v4 generators in `challenge/`; `matplotlib` is only
needed for the sky maps.
