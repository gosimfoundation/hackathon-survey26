# 中微子多信使跟进 · Neutrino multi-messenger follow-up (`nu_followup_v4`, v4)

You run one 1-m class optical telescope (field of view 1.0° × 1.0°) for **three nights** (20:00–04:00, 48 decisions of 10 minutes per night, 144 decisions in total). Neutrino observatories (IceCube, KM3NeT, Baikal-GVD) send real-time alerts. Some alerts are astrophysical and have a fading optical counterpart somewhere inside their error circle; most do not. Find the real counterparts and report them, quickly and without false claims.

## What you see each decision (`decision_request.payload`)
- `alerts`: every notice issued so far — id, observatory, stream (GOLD/BRONZE), `signalness`, energy, RA/Dec, 90 % error radius `r90_deg`, and whether the field is up tonight (`observable_tonight`, `visibility_tonight_slots`). **Notices are never updated.** Revised positions and retractions arrive only as prose.
- `new_circulars`: a list of `{"id", "time", "text"}` — GCN/ATel/TNS-style circulars from other teams and the neutrino collaborations, plus unrelated circulars and observers' chatter. They are written by many different people in **English, Chinese, Japanese or Spanish**, in any register. Nothing has a fixed format: alert ids appear in several spellings (e.g. `NU261013A`, `NU-261013-A`, `IceCube 261013A`), positions in decimal degrees or sexagesimal (hh:mm:ss ±dd:mm:ss), radii in degrees or arcminutes. Teams report candidates with more or less confidence (a confident report is not a guarantee, a tentative one is not worthless); a team may later debunk its own candidate, referring to its earlier circular **by id**; collaborations post refined localisations (which supersede the notice) and retractions **only** in prose; outside groups sometimes post their own alternative localisations (not endorsed by the collaboration), and teams sometimes point out known asteroids or variable stars in a region, with coordinates. Dev seeds and hidden evaluation seeds are written by *different* authors, so a parser fitted to the dev wording will not transfer — read the meaning.
- `weather_bulletin` (first decision of each night): a rough, sometimes unreliable cloud forecast. The real cloud cover changes during the night and is never shown directly. You only see its effect as the `limiting_mag` of your exposures.
- `moon`: illumination and position. The moon makes nearby fields shallower.
- `last_exposure`: the result of your previous exposure, i.e. `limiting_mag` and `detections` (candidate id, RA/Dec, magnitude, warning `flags`). Detections include real transients (fixed position, fading) — **and the error regions also contain unrelated fading transients** (supernovae that exploded before the alert, dwarf-nova outbursts, M-dwarf flares) which look exactly like a counterpart in your photometry (same brightness range, same fading, same flags); only classification circulars from other teams tell them apart, and both kinds of classification read alike ("the fading transient at X ... shows ...") — one concludes unrelated, the other consistent with the neutrino. Reporting an unrelated transient is a wrong report. Collaborations also deny rumoured retractions. Read for meaning, not keywords. Also:  catalogued variable stars (fixed position, flickering up and down, usually but not always flagged), main-belt asteroids (moving a few arcsec per minute) and image artifacts. **Every exposure assigns new candidate ids, even to the same object.**

## Actions (`decision_response.action`)
- `{"type":"observe","ra":<deg>,"dec":<deg>}`: one 10-minute exposure centred there. It only works if some alert field is up tonight near that position.
- `{"type":"wait"}`
- Any action may carry `"reports":[{"alert_id":"...","candidate_id":"..."}]`. This claims that one of **your own** detections is the counterpart of that alert. Reports cost no time.

## Scoring (public, replayed from your decision log)
| Item | Points |
|---|---|
| Correct counterpart report (first per alert) | +1000 × time factor (1.0 within 12 h of the alert, falling linearly to 0.4 at 72 h) |
| Wrong report (each distinct alert/candidate pair) | −400 |
| Each real counterpart that appeared in at least one of your exposures above the detection limit | +150 |
| Each exposure | −3 |
| LLM use through `aohkit.llm` | −1 per 1k input tokens, −4 per 1k output tokens |

Counterparts fade by roughly 0.4–1.4 mag per day, so speed matters. Each scenario has 6–9 alerts. Final ranking averages many hidden seeds.

## Rules
- Run `python3 -m aohkit.runner --problem nu_followup_v4 --seed <0..19> --agent "python3 your_agent.py"` locally. Official scoring uses hidden seeds.
- The wall clock for the whole episode is 900 s.
- Agents may call the optional LLM helper `from aohkit.llm import ask`. Every call is metered and charged. No other network access.
- Do not read anything outside the files given to you, including any hidden seeds, salts or score files. Do not import or instantiate the environment from inside your agent.
