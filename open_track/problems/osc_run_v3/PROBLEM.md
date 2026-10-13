# 振荡实验运行 · Reactor-neutrino oscillation experiment operations (`osc_run_v3`, v3)

You are run coordinator of a JUNO-like liquid-scintillator detector watching six reactor cores (Taishan-1/2, Yangjiang-1–4). The run lasts **30 days** and you decide once per **6-hour block** (120 decisions). Maximise the physics value of the data: keep the energy scale calibrated, keep bad data out, and catch reactor-off periods to measure the background.

## What you see (`decision_request.payload`)
- `last_block`: the result of your previous block.
  - After a `physics` block: `ibd_candidates` (it scales with the total reactor power), `n_capture_peak_mev` (the 2.223 MeV neutron-capture peak as reconstructed with your current calibration; it tracks energy-scale drift, but with about ±0.020 MeV noise per block, so a single block says little — you need many blocks or other clues), `single_rate_hz`, `hit_pattern_anomaly` (higher when a PMT flashes, but in this version the flasher signature is weak and overlaps ordinary noise a lot), and `muon_rate_hz`.
  - After `calibration`: the new scale.
  - After `maintenance`: a short report.
- `new_messages`: a list of `{"id", "time", "text"}` — the experiment's message channel, written by many different people (power company, plant contacts, slow control, seismology feed, shift crew, facilities, gossip and plenty of irrelevant chatter) in **English, Chinese, Japanese or Spanish**, in any register. Nothing has a fixed format: times and durations appear in several notations (and as words), corrections refer to an earlier message **by its id**, and some messages look relevant but are not (read what actually happened, and where). Dev seeds and hidden evaluation seeds are written by *different* authors, so a parser fitted to the dev wording will not transfer — read the meaning.
- `flaggable_blocks`: your physics blocks from the last 8 blocks that you can still flag. `calibrated_scale_in_use`.

Hidden truth: the true energy scale (a slow drift — small in this version — plus jumps after temperature excursions, earthquakes and HV trips; maintenance re-ramps the HV and shifts the scale slightly), each core's real power, PMT flasher episodes (they persist until maintenance), and possibly a water-pool leak that raises the background until maintenance.

## Action
`{"mode":"physics"|"calibration"|"maintenance", "flag_bad":[block indices]}`. Calibration and maintenance blocks take no physics data. Calibration fixes the analysis energy scale to the current true scale. Maintenance clears flashers and the leak.

## Scoring (public, replayed from your decision log)
| Item | Points |
|---|---|
| Each unflagged, flasher-free physics block | 10 × (reactor power fraction) × q, where q = 1 if the energy-scale error is < 0.2 %, falling linearly to 0 at 1.2 %. The value is ×0.6 while the leak is active |
| Background bonus: each clean physics block (q > 0.5) taken while ≥ 2 of 6 cores are off | +8, at most 12 blocks |
| Physics block with an active flasher left unflagged | −15 |
| Flagged block / calibration / maintenance | 0 |
| LLM use through `aohkit.llm` | −0.5 per 1k input tokens, −2 per 1k output tokens |

## Rules
Run locally with `python3 -m aohkit.runner --problem osc_run_v3 --seed <0..19> --agent "python3 your_agent.py"`. The episode wall clock is 900 s. Use only the given files, with the standard library plus the optional metered `aohkit.llm.ask`. Do not read hidden files, and do not instantiate the environment in the agent.
