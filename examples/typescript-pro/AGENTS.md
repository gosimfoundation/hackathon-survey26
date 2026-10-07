# AGENTS.md -- typescript-pro

Guide for AI coding assistants working in this project. Humans: see README.md / README.zh.md.

## What this is

A readable TypeScript (Node.js 22+, built-ins only) example agent for the GOSIM survey26 telescope-survey
challenge (`participant-agent-protocol-v4`). It is the module-by-module port of `../python-pro` and takes the
same decisions: a greedy, required-first planner makes every observe decision; a simple rule reports
instrument faults; an optional model reads free-text staff notes. Its only dependencies are `typescript` and
`@types/node`, and only for the build. Read `src/agent.ts` first: it is the stdin/stdout loop and owns waits,
fault reporting, pacing and the optional model stage.

## Module map (one per python-pro module)

```
src/agent.ts       agent.py        entry point: protocol loop, waits, FaultWatch (instrument-fault rule), pacing, staff-note wiring
src/planner.ts     planner.py      candidates -> anchors -> exposure time -> field -> program; learns factors and sky quality
src/skymath.ts     skymath.py      public sky maths (+ Python float semantics: %, round, sum)
src/logReader.ts   log_reader.py   optional model stage: staff notes -> closures / sectors to avoid / report times
src/llmClient.ts   llm_client.py   OpenAI-compatible chat client (built-in fetch; Kimi Coding Plan defaults)
src/packAgent.ts   pack_agent.py   zip this folder for upload (.env, node_modules and dist are never packed)
observer.project.json, package.json, tsconfig.json, .env.example
```

## Rules for changes

- Never read card files at run time. All information comes from stdin (catalogue, public score config,
  bulletins, forecasts, observation requests, your own hits).
- Never call the model per decision; `logReader.ts` sends each staff note once, in the background.
- The model is optional: without `OPENAI_API_KEY` (or `KIMI_API_KEY`), or with `OBSERVER_MODEL_DISABLED=1`,
  the agent runs on its rules only.
- Keep the CPU per decision small: the platform charges CPU time inside the agent's turns
  (`wallclock.remaining_real_cpu_seconds`); `pace()` in `agent.ts` lowers the number of anchors when it runs short.
- Containers whose iteration order matters (picks, pending predictions, neighbour cells) are `Map`s, because a
  plain object reorders integer-like keys. Keep it that way if you want to stay decision-identical with
  python-pro.

## Build and run

```bash
npm ci && npm run build      # tsc -> dist/ (the platform runs npm ci --include=dev, see observer.project.json)
node dist/agent.js           # what the platform runs (observer.project.json)
npm run pack                 # -> ../typescript-pro-agent.zip
```
