# v4 competition task cards: v4-a, v4-b, v4-c, v4-d (specs only)

**Status: trial / for review.** This directory carries only the **generator specs**
for the four trial v4 task cards, so that organizers can review the parameters and
rebuild the cards on their side. Built bundles (`config/` + `public/` + `truth/`),
smoke-run evidence and sky maps are deliberately **not** committed — regenerate them
from these specs when needed.

## Layout

```
cards/
  v4-a/spec/    card.json + the four v4_*.json generator configs
  v4-b/spec/    same
  v4-c/spec/    same
  v4-d/spec/    same
```

Each `spec/` is a complete, self-contained generator input set: `card.json`
(name / card_id / scenario_slug / phase / stress / wallclock) plus the catalog,
weather, fiber and score configs. The trial builder used to produce the trial
bundles is kept outside this repository; organizers can regenerate any card by
feeding a spec to the v4 card bundle tooling (`challenge/v4_bundle.py` semantics:
hashed per-stream seeds, `cross_validate_generator_configs`, bundle layout
`config/` + `public/` + `truth/`).

## Card parameters

| | v4-a | v4-b | v4-c | v4-d |
|---|---|---|---|---|
| site | VISTA/Paranal -24.62 deg | Cape Town -33.92 deg | Mauna Kea +19.82 deg | Nemo (fictional) -45 deg |
| footprint | 3 components / 6000 deg2 | 2 / 8000 deg2 | 4 / 4000 deg2 | 3 / 6000 deg2 |
| targets (required) | 30000 (1500) | 50000 (2500) | 30000 (1500) | 30000 (1500) |
| season | 2026-10-01 -> 2027-02-01 | 2027-06-01 -> 2027-12-01 | 2026-12-01 -> 2027-04-01 | 2027-01-01 -> 2028-01-01 |
| fibres / area | 16 (4x4) / 0.4 deg2 | 25 (5x5) / 0.064 deg2 | 9 (3x3) / 0.7 deg2 | 100 (10x10) / 0.06 deg2 |
| f0 / T0 | 0.5 / 900 | 0.8 / 1000 | 0.5 / 900 | 0.5 / 900 |
| stress | no | no | no | yes (data_loss + pointing_offset) |
| observation requests | 6 x (8 targets, min 6, reward 100) | same | same | same |

Only v4-b differs in the score config (f0/T0). `program` multipliers, `uniformity.weight`,
`required`, `reporting`, `background_closure` and `publication` are identical across all four.

## Known issue

- v4-d's footprint has a detached fragment: ~10 targets near RA 190-215 deg,
  dec < -55 deg fall outside every component polygon. Diagnose and regenerate v4-d
  before any participant-facing use.

## Before these can be formal cards

1. **Rotate the seeds.** The specs carry trial seeds (`20261001`, `20260930`,
   `20261201`, `20270101`), and v4-a's seed is byte-identical to the seed committed in
   `challenge/reference/v4/v4_catalog_config.json`. Anyone with this public repository
   can therefore rebuild these cards' hidden weather. Formal cards need 128-bit secrets
   injected from outside git, with the `seed` field removed from `spec/`.
2. **Register**, per card: a `public.scenarios` row (contract `v4-score-v1`,
   `global_wallclock_seconds` 900, `weather_public`/`forecasts_public`/`events_public`
   all false); only `config/` and `public/` uploaded to `scenarios/<slug>/` (the phase
   switch refuses a formal card that has files outside those two directories); the full
   `config/`+`public/`+`truth/` bundle zipped to
   `observer-scenarios/<scenario_id>/<digest>.zip` with a
   `private.observer_scenario_bundles` row; then
   `scripts/configure-v4-phases.py --formal v4-a,v4-b,v4-c,v4-d --apply`.
3. **Do not use the admin "rotate seed" action on a v4 card.** It runs
   `worker/main.py:process_scenario_job`, which is v3-only and has no contract guard: it
   would overwrite `scenarios/<slug>/` with a v3 scenario and flip the row's contract,
   while the private v4 bundle stays untouched.
