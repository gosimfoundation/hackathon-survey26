# python-pro -- a readable rule-based example agent for participant-agent-protocol-v4

[中文说明见 README.zh.md](README.zh.md)

An example agent for the GOSIM survey26 telescope-survey challenge that shows the essentials in a few hundred
lines of standard-library Python: required targets first, basic sky maths, a conservative instrument-fault rule
and an optional model that reads staff notes. It is meant as a starting point to read and improve, not as a
competitive entry. It uses only what the protocol gives an agent at run time (catalogue, public score
configuration, bulletins, forecasts, observation requests and its own results); it never reads card files.

## Results (local engine, rules only, `OBSERVER_MODEL_DISABLED=1`)

| Card | A | B | C | D | A1 | B1 | C1 | D1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| python-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,659 |

Scores move by a few percent between runs (machine speed changes the CPU budget, fault timing varies).

## Layout

```
agent.py          entry point: protocol loop, waits, the instrument-fault rule (FaultWatch), pacing
planner.py        greedy required-first scheduler; learns factors and sky quality from the hits
skymath.py        public sky maths: sidereal time, alt/az, gnomonic projection, fibre grid, Moon
log_reader.py     optional model stage: reads free-text staff notes attached to observation requests
llm_client.py     OpenAI-compatible chat client (standard library, background threads)
observer.project.json   platform manifest (python3 -u agent.py)
pack_agent.py     zip this folder for upload (.env is never packed)
.env.example      copy to .env and set an API key for local runs with the model
```

## How it decides (planner.py)

1. **Candidates.** Every target that is above the altitude limit now and in ten minutes, and still has value:
   `value = 50 (unfinished required target: the penalty it avoids) + weight x (1 - factor so far) + request reward`.
   Its priority multiplies the value by *sky quality now / best quality it can ever get* (airmass and Moon from
   the public formulas, so targets near transit and away from the Moon come first) and by an urgency factor
   when few nights are left for it.
2. **Exposure time.** For each of the best few candidates (the *anchors*) the planner computes the exposure
   that brings it to its goal: completion factor 0.5 x 1.3 for a required target, factor 0.9 (at most 30
   minutes) for the others. A required target that cannot reach its goal in one hour tonight waits for a better sky.
3. **Field.** The pointing puts the anchor on a central fibre; every other fibre takes the neighbour that
   gains most from the same exposure (targets near a fibre edge are skipped). The anchor whose field earns
   the most per second wins. That is the whole search: no refinement, no look-ahead.
4. **Program.** DARK / BRIGHT / BACKUP from the predicted sky quality of the assigned targets.

Learning: a hit's score is `weight x factor x program multiplier`. The planner keeps a conservative factor per
target (it assumes the program matched) and the *sky quality* = observed / predicted factor of unsaturated
hits; the median of the last eight exposures scales all predictions.

Bulletins: rain or storm over the whole sky closes the site (wait); a terrain obstruction or rocket launch
blocks its direction low in the sky; directional weather down-weights its sector.

## Instrument faults (agent.py, `FaultWatch`)

A fault lowers the instrument efficiency until somebody reports it; weather and earthquakes lower the quality
too, and a report does not repair those. Weather changes from night to night, a fault stays. The rule compares
each exposure's quality with the usual level since the last repair (90th percentile of exposures without
all-sky weather: a clear night with a healthy instrument) and reports on

- a collapse: two exposures in a row below 10 % of the usual level, or
- a lasting drop: the median quality of each of the last two observed nights (at least four exposures each,
  no all-sky weather) below 55 % of the usual level.

Only exposures after the last report count as evidence, so one episode is never reported twice. Once the
free wrong reports are used up, reports are at least 120 hours apart (a fault lasts until it is reported,
so a late report still pays).

## Optional model: staff notes (log_reader.py)

Some cards attach longer free-text notes from the observatory staff to observation requests. With an API key
the agent sends every new note once to the model and turns the JSON answer into three rules: announced
closures -> wait, bad sectors -> down-weight, announced instrument problems -> report. Calls run on
background threads and never stall the survey; without a key, or when the platform runs an evaluation
without a model (`OBSERVER_MODEL_DISABLED=1`), the agent simply runs on its rules.

```
OPENAI_API_KEY=sk-...                            # optional (KIMI_API_KEY also accepted)
OPENAI_BASE_URL=https://api.kimi.com/coding/v1   # default; outside mainland China: https://api.kimi.ai/coding/v1
OPENAI_MODEL=k3                                  # default
```

On the platform `OPENAI_BASE_URL` / `OPENAI_API_KEY` are injected automatically.

## Running locally

```bash
python3 ../_local/runner/run_local.py --inherit-env --card ../_local/cards/L1 --agent "python3 agent.py" --agent-cwd .
python3 pack_agent.py --out ../python-pro-agent.zip
```

## Ideas for doing better

- **Search more.** Try more pointings per decision (several fibres for the anchor, dense patches of remaining
  science, small shifts) and more exposure times, and price telescope time instead of maximising gain per second.
- **Plan the season.** Faint required targets need the best nights; decide which nights to spend on which
  part of the sky instead of acting greedily.
- **Read the program band from the hits.** A saturated hit shows the program multiplier exactly, so it tells
  whether the declared program matched.
- **Better fault detection.** Weather and an instrument fault look alike in one exposure; compare quality
  with the sky band, across directions and across nights, and use the free reports wisely.
- **Use the model more**, e.g. for the forecast or to judge a suspected fault.

## License

Task cards, simulated data, evaluation code and the example projects are licensed under
[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/); please cite the GOSIM 2026 Agentic
Observer Hackathon (https://create.gosim.org/survey26/). See `../LICENSE.md`.
