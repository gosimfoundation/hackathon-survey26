# AGENTS.md -- python-pro

Guide for AI coding assistants working in this project. Humans: see README.md / README.zh.md.

## What this is

A readable, standard-library-only Python example agent for the GOSIM survey26 telescope-survey challenge
(`participant-agent-protocol-v4`). A greedy, required-first planner makes every observe decision; a simple
rule reports instrument faults; an optional model reads free-text staff notes. Read `agent.py` first: it is
the stdin/stdout loop and owns waits, fault reporting, pacing and the optional model stage.

## Module map

```
agent.py          entry point: protocol loop, waits, FaultWatch (instrument-fault rule), pacing, staff-note wiring
planner.py        candidates -> anchors -> exposure time -> field -> program; learns factors and sky quality
skymath.py        public sky maths: sidereal time, alt/az, gnomonic projection, fibre grid, Moon
log_reader.py     optional model stage: staff notes -> closures / sectors to avoid / report times
llm_client.py     OpenAI-compatible chat client (Kimi Coding Plan defaults)
observer.project.json, pack_agent.py, .env.example
```

## Rules for changes

- Never read card files at run time. All information comes from stdin (catalogue, public score config,
  bulletins, forecasts, observation requests, your own hits).
- Never call the model per decision; `log_reader.py` sends each staff note once, on a background thread.
- The model is optional: without `OPENAI_API_KEY` (or `KIMI_API_KEY`), or with `OBSERVER_MODEL_DISABLED=1`,
  the agent runs on its rules only.
- Keep the CPU per decision small: the platform charges CPU time inside the agent's turns
  (`wallclock.remaining_real_cpu_seconds`); `agent._pace` lowers the number of anchors when it runs short.
