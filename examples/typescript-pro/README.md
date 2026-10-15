# typescript-pro -- a readable rule-based example agent for participant-agent-protocol-v4

[中文说明见 README.zh.md](README.zh.md)

The TypeScript (Node.js 22+) port of [`../python-pro`](../python-pro): the same short, readable example agent
for the GOSIM survey26 telescope-survey challenge -- required targets first, basic sky maths, a conservative
instrument-fault rule and an optional model that reads staff notes. Same strategy, same constants, one module
per python-pro module. Its only dependencies are `typescript` and `@types/node`, and only for the build. It is
meant as a starting point to read and improve, not as a competitive entry. It uses only what the protocol
gives an agent at run time (catalogue, public score configuration, bulletins, forecasts, observation requests
and its own results); it never reads card files.

## Results (local engine, rules only, `OBSERVER_MODEL_DISABLED=1`)

| Card | A | B | C | D | A1 | B1 | C1 | D1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| typescript-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,659 |
| python-pro | 17,962 | 30,734 | 17,884 | 26,695 | 11,689 | 16,037 | 11,058 | 26,809 |

Cards A-D, A1-C1: the same score as python-pro (on card A the same 2,423 actions). D1, the longest card, ran on a
heavily loaded machine, where pacing tried fewer anchors. Scores move by a few percent between runs (machine speed
changes the CPU budget and with it the number of anchors tried, fault timing varies).

## Layout

```
src/agent.ts       agent.py        entry point: protocol loop, waits, the instrument-fault rule (FaultWatch), pacing
src/planner.ts     planner.py      greedy required-first scheduler; learns factors and sky quality from the hits
src/skymath.ts     skymath.py      public sky maths: sidereal time, alt/az, gnomonic projection, fibre grid, Moon
src/logReader.ts   log_reader.py   optional model stage: reads free-text staff notes attached to observation requests
src/llmClient.ts   llm_client.py   OpenAI-compatible chat client (built-in fetch, calls run in the background)
src/packAgent.ts   pack_agent.py   zip this folder for upload (.env, node_modules and dist are never packed)
observer.project.json   platform manifest: image node:22-slim, build `npm ci --include=dev` + `npm run build`, run `node dist/agent.js`
.env.example      copy to .env and set an API key for local runs with the model
```

## How it decides (src/planner.ts)

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

Pace: the platform charges the CPU time spent inside the agent's turns. `agent.ts` measures the CPU per
decision and lowers the number of anchors (6 at most) when the remaining budget runs short.

## Instrument faults (src/agent.ts, `FaultWatch`)

A fault lowers the instrument efficiency until somebody reports it; weather and earthquakes lower the quality
too, and a report does not repair those. The rule compares each exposure's quality with the usual level since
the last repair (90th percentile of the exposures without all-sky weather) and reports only:

- after two exposures in a row below 10 % of the usual level (a collapse weather rarely explains), or
- when the median quality of each of the last two observed nights (at least four clean exposures each) is
  below 55 % of the usual level (weather changes from night to night, a fault stays).

Only exposures after the last report count as evidence, so one episode is never reported twice. Once the
free wrong reports are used up, it reports at most once every five days.

## Optional model: staff notes (src/logReader.ts)

Some cards attach longer free-text notes from the observatory staff to observation requests. With an API key
the agent sends every new note once to the model and turns the JSON answer into three rules: announced
closures -> wait, bad sectors -> down-weight, announced instrument problems -> report. Calls run in the
background (promises on the event loop) and never stall the survey; without a key, or when the platform runs
an evaluation without a model (`OBSERVER_MODEL_DISABLED=1`), the agent simply runs on its rules.

```
OPENAI_API_KEY=sk-...                            # optional (KIMI_API_KEY also accepted)
OPENAI_BASE_URL=https://api.kimi.com/coding/v1   # default; outside mainland China: https://api.kimi.ai/coding/v1
OPENAI_MODEL=k3                                  # default
```

On the platform `OPENAI_BASE_URL` / `OPENAI_API_KEY` are injected automatically.

## Running locally

```bash
npm ci && npm run build                          # tsc -> dist/
python3 ../_local/runner/run_local.py --inherit-env --card ../_local/cards/L1 --agent "node dist/agent.js" --agent-cwd .
npm run pack                                     # -> ../typescript-pro-agent.zip
```

## TypeScript notes

- **Same numbers as Python.** `src/skymath.ts` reproduces Python's float `%`, `round()` and `sum()`
  (compensated summation since Python 3.12), sorts break ties like Python's tuple sorts, and containers whose
  iteration order matters are `Map`s (a plain object sorts integer-like keys). That is why both agents take
  the same decisions.
- **Async instead of threads.** python-pro reads staff notes on background threads; here the calls are
  promises that progress while the agent waits for the next line on stdin.
- **Platform build.** The platform runs the build with the manifest's environment and a read-only home
  directory, so the manifest sets `NPM_CONFIG_CACHE=/workspace/.npm-cache` and installs with
  `npm ci --include=dev` (the TypeScript compiler is a dev dependency).

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
