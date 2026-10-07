# AGENTS.md -- rust-pro

Guide for AI coding assistants working in this project. Humans: see README.md / README.zh.md.

## What this is

The Rust port of the readable rule-based example agent `../python-pro` for the GOSIM survey26 telescope-survey
challenge (`participant-agent-protocol-v4`). Same strategy, same constants: a greedy, required-first planner
makes every observe decision; a simple rule reports instrument faults; an optional model reads free-text
staff notes. Read `src/main.rs` first: it is the stdin/stdout loop and owns waits, fault reporting, pacing
and the optional model stage.

## Module map (one file per python-pro module)

```
src/main.rs        agent.py        entry point: protocol loop, waits, FaultWatch (instrument-fault rule), pacing, staff-note wiring
src/planner.rs     planner.py      candidates -> anchors -> exposure time -> field -> program; learns factors and sky quality
src/skymath.rs     skymath.py      public sky maths: sidereal time, alt/az, gnomonic projection, fibre grid, Moon
src/log_reader.rs  log_reader.py   optional model stage: staff notes -> closures / sectors to avoid / report times
src/llm_client.rs  llm_client.py   OpenAI-compatible chat client (Kimi Coding Plan defaults)
observer.project.json, pack_agent.py, .env.example
```

## Rules for changes

- Never read card files at run time. All information comes from stdin (catalogue, public score config,
  bulletins, forecasts, observation requests, your own hits).
- Never call the model per decision; `log_reader.rs` sends each staff note once, on a background thread.
- The model is optional: without `OPENAI_API_KEY` (or `KIMI_API_KEY`), or with `OBSERVER_MODEL_DISABLED=1`,
  the agent runs on its rules only.
- Keep the CPU per decision small: the platform charges CPU time inside the agent's turns
  (`wallclock.remaining_real_cpu_seconds`); `ObserverAgent::pace` lowers the number of anchors when it runs short.
- If you change the strategy, say so: the port is meant to stay decision-for-decision equal to python-pro
  (same order of operations and tie-breaking), which makes it easy to check against the Python version.
- Build with `cargo build --release --locked` (the platform does the same); keep dependencies minimal
  (serde_json, ureq, libc) and never commit `target/` or `.env`.
