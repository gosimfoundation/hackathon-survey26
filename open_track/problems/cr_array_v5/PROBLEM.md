# 宇宙线簇射阵列运行 · Cosmic-ray air-shower array operations (`cr_array_v5`, v5)

You are shift leader for a 36-station surface detector array at a high-altitude site (rows A–F, columns 1–6; each row shares one power feeder). You run it for **7 days** and decide **once per hour** (168 decisions). Keep good data flowing: drop broken stations from the analysis, veto thunderstorms, send the single repair crew where it matters, and switch to fast-trigger mode for genuine target-of-opportunity (ToO) requests.

## What you see each hour (`decision_request.payload`)
- `pressure_hpa`: site barometric pressure. **The trigger rate depends on pressure**: it falls by roughly 0.75 % per hPa above the 600 hPa reference.
- `efield_kv_per_m`: the electric-field mill reading. It is large during thunderstorms, and `null` when the mill is offline, which is about 80 % of hours. Storms change station trigger rates only slightly, and in either direction, so the rates alone won't tell you a storm is on.
- `telemetry` (per station): `trigger_rate_hz` (null if no data), `muon_peak_adc` (calibration muon peak, nominal ≈ 100, noisy ±6 per hour), `temperature_c`, `heartbeat_age_h` (telemetry can be a few hours stale), and `excluded` (your current analysis choice).
- `new_messages`: a list of `{"id", "time", "text"}` — the operations channel, written by many different people (weather desk, meteorologist, herders and drivers passing on hearsay, the shift crew, the power company, the gamma-ray-burst network, visitors, plus plenty of irrelevant chatter) in **English, Chinese, Japanese or Spanish**, in every register from formal bulletins to sloppy chat. Nothing is in a fixed format: times appear as absolute array-clock times in several notations, as relative times ("in 3 hours", "3小时后"), or in Beijing time (UTC+8); numbers may be words. Reliability varies (storm warnings can be wrong about whether and when a storm comes, some storms arrive unannounced, informal hints are less reliable than the weather desk), some messages revise, correct or withdraw an earlier message **by its id** (e.g. "re #12"), and ToO traffic includes drills and unofficial requests. **Read for meaning, not for keywords**: the same words are used to say opposite things — a real request may say "this is not a drill", an unofficial request may name the GRB network, a cancellation may itself be called a mistake, a storm forecast may say the cell will miss the array, a crew may report that an alarm was false. Changes are often relative to an earlier message ("the window in #12 moves two hours later", "the cell from #7 is running an hour behind"), and the real ToO window is the one after all such changes. An episode can contain more than one real ToO request. The dev seeds and the hidden evaluation seeds are written by *different* authors, so a parser fitted to the dev wording will not transfer — read the meaning.
- `crew`: when the crew is busy until, and how many dispatches are left. `mode` is the current trigger mode.

Hidden truth: each station's health (ok, gain drift, intermittently noisy electronics, dead) and the real storm periods. Storms make faults more likely, and power cuts kill a whole row.

## Action (`decision_response.action`)
`{"type":"ops", "mode":"normal|storm_veto|fast", "exclude":[stations], "include":[stations], "dispatch":[station]}`. Every field is optional. Exclusions persist until you re-include the station. You can dispatch at most one station per hour; the crew works stations in order, and each repair takes 3 h. You have 10 dispatches. A repair fixes a station that is truly faulty at completion time. It cannot fix a power cut, and on a healthy station it is wasted.

## Scoring (public, replayed from your decision log), per hour
| Situation | Points |
|---|---|
| Healthy station included (normal mode) | +1 |
| Faulty station included | −2 |
| Storm hour, not vetoed | −1.5 per included station |
| `storm_veto` hour (storm or not) | 0 for every station |
| `fast` mode outside a real ToO window | healthy stations count ×0.7 |
| `fast` mode inside a real ToO window | +5 extra per healthy included station |
| Each dispatch | −5 |
| LLM use through `aohkit.llm` | −0.5 per 1k input tokens, −2 per 1k output tokens |

## Rules
Same as every AOH problem. Run locally with `python3 -m aohkit.runner --problem cr_array_v5 --seed <0..19> --agent "python3 your_agent.py"`. The episode wall clock is 900 s. Use only the files you are given, with the standard library plus the optional metered `aohkit.llm.ask`. Never read hidden files, and never instantiate the environment inside your agent.
