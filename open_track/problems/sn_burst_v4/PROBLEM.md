# 超新星中微子爆发预警 · Supernova neutrino burst early warning (`sn_burst_v4`, v4)

You are the duty officer of a SNEWS-like alert network of four neutrino detectors: Super-K (`SK`), `KamLAND`, `JUNO` and `IceCube`. You stand watch for **4 days** and decide every **15 minutes** (384 decisions). This is a **SNEWS exercise period**: 3–5 realistic supernova bursts (0.2–65 kpc, random directions, some preceded by a pre-supernova ramp) are injected, unannounced, into the live data, and you must treat them exactly like real events. When a burst happens, every running detector sees it in the same 10-second window. Alert fast, point the astronomers to the right place, and never cry wolf.

## What you see (`decision_request.payload`)
- `detectors[d]`: whether detector `d` is running, plus `last_window` for the previous 15 minutes: `max_10s_counts` (largest 10-s count), `mean_bkg_per_10s`, and `ibd_singles_rate_per_h` (low-energy inverse-beta-decay singles rate).
- `excess_arrival_ms`: present when some detector had a large excess. It gives the arrival time of each excess on a common clock (ms). A real burst reaches detectors at different times: `t_i = t0 − (r_i · n)/c`, with detector positions in `initialize.detectors` and `c` = 299.792458 km/ms. Unrelated excesses have unrelated times.
- `sk_elastic_pointing`: a Super-K direction estimate with its 1σ error. It is produced for any large Super-K excess (for an instrumental excess the direction is meaningless). For a distant burst it may be missing.
- `new_messages`: a list of `{"id", "time", "text"}` — the network's message channel: detector shift crews (calibrations, maintenance, spallation, radon, noise storms), network operations and IT, astronomers, social-media rumours, plenty of irrelevant chatter, and the replies to your `check` requests. Written by many different people in **English, Chinese, Japanese or Spanish**, in any register; nothing has a fixed format (times may be absolute in several notations, or relative like "30 minutes ago"); some messages revise an earlier one **by its id**; and some look relevant but are not (read *what* was affected). Dev seeds and hidden evaluation seeds are written by *different* authors, so a parser fitted to the dev wording will not transfer — read the meaning.
- **Pipeline tests (new in v4).** Besides the scored exercise injections, the coordination team occasionally injects *pipeline-test* signals. In the data they are indistinguishable from a real burst (all running detectors, consistent timing and pointing). They are not part of the exercise: an alert on one counts as a false burst alert. Coordination announces them on the channel, usually beforehand and sometimes only shortly afterwards; announced tests can also be cancelled. Other "tests" (for example of the alert e-mail system) inject nothing into the data.
- `checks_left`.

Hidden truth: whether and when a burst happens, plus its distance (0.2–65 kpc) and direction. Very close progenitors (≲ 1 kpc) emit **pre-supernova neutrinos**: the singles rate in KamLAND and JUNO rises over the hours before collapse. Also hidden: maintenance outages (sometimes longer than announced), calibrations (sometimes unannounced), coincident but unrelated excesses in two detectors, very large IceCube noise storms, and network timing glitches that fire 2–3 detectors at once with near-identical arrival times. The glitches are announced by network operations, sometimes one or two steps late. A KamLAND-only radon episode looks like a pre-supernova rise.

## Actions
- `{"type":"wait"}`
- `{"type":"alert","level":"burst","direction":{"ra":deg,"dec":deg}}`: `direction` is optional and uses the fixed frame of the detector positions.
- `{"type":"alert","level":"pre_sn"}`
- `{"type":"check","detector":"SK"}`: asks that shift crew about the previous window. Their reply arrives at the next decision. It costs 20 points, and you have at most 12.

## Scoring (public, replayed from your decision log)
| Item | Points |
|---|---|
| Per injected burst: first burst alert within 1 h after it | +1000, minus 25 % per 15-min step of delay (alerting at the first decision after the burst window is on time) |
| Direction attached to that alert | +400 × max(0, 1 − error/60°) |
| Burst missed | −500 each |
| False burst alert (not within 1 h after any burst; alerts within 2 h of each other count once) | −750 |
| Per pre-SN signal: first `pre_sn` alert while it is running | up to +500 (full credit at ≥ 2 h before the burst) |
| `pre_sn` alert outside any pre-SN signal (grouped per 2 h) | −250 |
| Each check | −20 |
| LLM use through `aohkit.llm` | −1 per 1k input tokens, −4 per 1k output tokens |

Ranking averages many hidden seeds.

## Rules
Run locally with `python3 -m aohkit.runner --problem sn_burst_v4 --seed <0..19> --agent "python3 your_agent.py"`. The episode wall clock is 900 s. Use only the given files, with the standard library plus the optional metered `aohkit.llm.ask`. Do not read hidden files, and do not instantiate the environment inside the agent.
