# v4 practice task cards: v4-practice-a, -b, -c, -d (specs only)

**Status: practice cards (Playground α, β, γ, δ).** These are debugging cards for
participants, not the hackathon cards A–D (`v4-a`..`v4-d`) or the hidden cards E–H,
which are generated separately with secret seeds. This directory carries only the
**generator specs** for the four practice cards, so that organizers can review the parameters and
rebuild the cards on their side. Built bundles (`config/` + `public/` + `truth/`),
smoke-run evidence and sky maps are deliberately **not** committed — regenerate them
from these specs when needed.

## Layout

```
cards/
  v4-practice-a/spec/    card.json + the four v4_*.json generator configs
  v4-practice-b/spec/    same
  v4-practice-c/spec/    same
  v4-practice-d/spec/    same
```

Each `spec/` is a complete, self-contained generator input set: `card.json`
(name / card_id / scenario_slug / phase / stress / wallclock) plus the catalog,
weather, fiber and score configs. `scripts/build-v4-practice-cards.py OUT --zip` builds
the bundles (`challenge.v4_bundle.build_spec_bundle`: catalogue -> weather -> observation
requests, bundle layout `config/` + `public/` + `truth/`) and `--pages` writes the card pages
`web/src/content/taskcard.<alpha|beta|gamma|delta>.v4.<en|zh>.md` from the specs
(tests/test_v4_practice_cards.py fails if a page and its spec disagree). `card.json` decides
`stress`: the weather config's `stress_tests.enabled` is overridden by it.

## Card parameters

| | v4-practice-a (α) | v4-practice-b (β) | v4-practice-c (γ) | v4-practice-d (δ) |
|---|---|---|---|---|
| site | VISTA/Paranal -24.62 deg | Cape Town -33.92 deg | Mauna Kea +19.82 deg | Nemo (fictional) -45 deg |
| footprint | 3 components / 6000 deg2 | 2 / 8000 deg2 | 4 / 4000 deg2 | 3 / 6000 deg2 |
| targets (required) | 30000 (1500) | 50000 (2500) | 30000 (1500) | 30000 (1500) |
| season | 2026-10-01 -> 2027-02-01 | 2027-06-01 -> 2027-12-01 | 2026-12-01 -> 2027-04-01 | 2027-01-01 -> 2028-01-01 |
| fibres / area | 16 (4x4) / 0.4 deg2 | 25 (5x5) / 0.064 deg2 | 9 (3x3) / 0.7 deg2 | 100 (10x10) / 0.06 deg2 |
| f0 / T0 | 0.5 / 900 | 0.8 / 1000 | 0.5 / 900 | 0.5 / 900 |
| stress | no | no | no | yes (data_loss + pointing_offset) |
| observation requests | 6 x (8 targets, min 6, reward 100) | same | same | same |

Only v4-practice-b differs in the score config (f0/T0). `program` multipliers, `uniformity.weight`,
`required`, `reporting`, `background_closure` and `publication` are identical across all four.

## Sky map of v4-practice-d (resolved)

The ~10 targets near RA 180–186 deg, dec < −55 deg that looked like a detached fragment
are inside the footprint: they belong to the component centred at (150, −50), which
reaches just past RA 180. The generator's spherical containment test accepts every one
of the 30000 targets. Only the map was misleading: the Mollweide map was centred on
RA 0, so that component was drawn in two pieces on opposite edges. `challenge/v4_sky_map.py`
now recentres the map so that no component straddles the seam (RA 270 for this card).

## Registering them as practice cards

1. **Seeds are public.** Practice cards publish their full file set (`config/`, `public/`
   and `truth/`), so the trial seeds in `spec/` (`20261001`, `20260930`, `20261201`,
   `20270101`) are fine here. Never reuse these specs or seeds for a hackathon or hidden
   card: anyone with this public repository can rebuild them.
2. **Register**, per card: a `public.scenarios` row with slug `v4-practice-<x>`
   (contract `v4-score-v1`, `global_wallclock_seconds` 900, weather, forecasts and events
   public), the bundle ZIP as its evaluation bundle, `config/`, `public/` and `truth/` in
   the public `scenarios` bucket under the slug, and the card parked in the sealed staging
   phase until the practice phase is switched to the practice set with
   `scripts/configure-v4-phases.py --practice ...`. Do not use the slugs `v4-a`..`v4-h`:
   they are the registered hackathon and hidden cards.
3. **Do not use the admin "rotate seed" action on a v4 card.** It runs
   `worker/main.py:process_scenario_job`, which is v3-only and has no contract guard: it
   would overwrite `scenarios/<slug>/` with a v3 scenario and flip the row's contract,
   while the private v4 bundle stays untouched.
