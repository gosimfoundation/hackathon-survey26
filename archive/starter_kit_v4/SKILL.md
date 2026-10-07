# SKILL: build, test and submit an Agent Observer v4 agent

For coding agents (Claude Code, Codex, Cursor, ...) working in this kit. Follow the steps in order.
Python 3.9+ standard library only. Run commands from the kit folder. Read `README.md` for the full rules.

## 1. Check the kit works

```
python3 --version
python3 local_runner.py --quiet
python3 local_runner.py --agent examples/idle_agent.py --quiet
```

Expected on `cards/demo` (the public demo card at Paranal, Chile (virtual), 7 nights, 2,400 targets):
baseline `"termination_reason": "survey_complete"`, `"total": 1082.572141`, `"required_missing": 1`,
and `"observation_requests_completed": 1`;
idle agent `"total": -6200.0`. Exit code 2 means `agent_error`: read `"error"` and `run_output/agent.log`.

## 2. Know the contract (`participant-agent-protocol-v4`)

- stdin/stdout, one JSON object per line, flush after each line. Logs go to stderr only.
- Messages in: `initialize` (once, no reply), `decision_request` (reply once, same `decision_sequence`),
  `finish` (once, no reply; stdin then closes; exit within 30 s).
- Every reply: `{"protocol_version": "participant-agent-protocol-v4", "message_type": "decision_response",
  "decision_sequence": <same int>, "action": ..., ...}`.
- Actions:
  - `observe`: `pointing {alt_deg, az_deg}`, `assignments {"<fibre 0-15>": "<target_id>"}` (each target
    once, each fibre once), `duration_seconds` 60–3600 (integer), `program` `DARK|BRIGHT|BACKUP` (optional,
    default `BACKUP`). No other keys. The exposure may cross slots within a night, but stops at
    that night's final slot end; its score uses the actual elapsed seconds, even if fewer than 60.
  - `wait`: `duration_seconds` 60–3600, or `until_utc` (UTC ending in `Z`, later than `now_utc`). Use
    `until_utc` for daytime.
  - `report`: the instrument has an unrepaired fault now (+100 if true; the first 2 false reports
    after each correct report are free on the demo card, then −150 each). The next request arrives
    at the same simulated time and gives `correct`, `repaired`, and `score_delta` in `last_result`
    and a `report_result` notice in `new_messages`. Read the free threshold from
    `scoring.reporting.false_report_free_allowance` and the action cap from
    `scoring.reporting.max_consecutive_reports`. A further report after the cap ends as
    `agent_error`. `observe` or `wait` resets only the consecutive-action count; only a correct
    report resets the false-report count.
  - `finish`: end the survey.
- Any invalid reply (including an unknown key) ends the run as `agent_error` (the score so far still
  counts). Validate before sending.
- Still computing when the wall clock runs out: the process is stopped at once, with no `finish`.
- Wall clock: 900 s per card on the platform, starting at the first request. `payload.wallclock.remaining_seconds`.
  A full season can be about 5,000 decisions: keep each decision under about 100 ms. No model call per decision.

## 3. Know the score

- factor = min(feature_flux × duration × q / 450, 1); score = science_weight × factor × program_bonus.
- q is the hidden sky/instrument quality; learn it from `last_result.hits` (each hit has its score).
- Time-limited requests arrive in `new_messages` and remain in `active_requests`. Observe their named
  catalogue targets before `deadline_utc`; attribution is automatic and no `request_id` action field exists.
- program_bonus: DARK 1.20, BRIGHT 1.12, BACKUP 1.06 if the declared program matches the sky band, else 1.0.
- Only the best exposure per target counts. Required target with best factor < 0.5: −50 each.
- −200 × (1 − Jain index) over 10° RA bands. Spread observations across right ascension.

## 4. Improve the agent

Edit files in `agent/` only (`baseline_agent.py` is the entry point; `planner.py` holds the strategy and
its tunable constants; `skymath.py` has the exact geometry). After each change:

```
python3 local_runner.py --quiet --out run_output
```

Compare `total`, `required_missing`, `targets_observed` and `wall_seconds`. Keep `wall_seconds` far below
the wall clock: a formal card can be much larger than the demo card.

Do not read `cards/` from the agent. On the platform the agent only has its own folder.

## 5. Optional: use a model

`agent/llm_hook.py` calls `OPENAI_BASE_URL/chat/completions` with `OPENAI_API_KEY` and model `OPENAI_MODEL`.
On the platform these are the variables your team saved in Participate → Keys and network (or with
`survey26 env model --provider … --key - --model …`); the call goes directly to your provider (the platform
sets `HTTPS_PROXY`), and the model must be a name that provider supports. `OBSERVER_API_URL` / `OBSERVER_RUN_TOKEN` are the platform's session interface, not a model endpoint; do not send model requests to them. Turn it on with `"USE_LLM": "1"` in `agent/observer.project.json`. Keep calls rare (once per night
or for rare decisions), with short timeouts and a rule-based fallback. For local tests put the variables
in `agent/.env`. Never commit or pack `.env`.

## 6. Package and submit

```
python3 pack_agent.py --out ../my-agent.zip
```

The ZIP has `observer.project.json` at its root with `"protocol": "jsonl-v4"` and
`"run": ["python3", "-u", "baseline_agent.py"]`. Upload it on the website's Participate page
(or push the `agent/` folder to a GitHub repository with `observer.project.json` at its root).
If you add packages, add a `build` step, e.g. `["pip", "install", "-r", "requirements.txt"]`.

## Sophon · easter egg (optional, unscored)

**Sophon · 彩蛋题** 主线之外，还有一道不计分的题。值班日志里有人说：有几晚的读数，好得不像这面镜子拍出来的。评测运行时，环境变量里会有一张通行证 `SOPHON_RUN_TOKEN`。看懂那几晚，再把你看到的告诉夜班看守，联系方式见 CLI 文档。不影响分数和奖项，赛后也开放。目前还没人走完。可以让你的 agent 试试，也许没那么难，也许没那么容易。

**Sophon · Easter egg** Beyond the main track there is one more problem, and it is not scored. Someone wrote in the duty log: on a few nights the readings were too good to have come from this mirror. While an evaluation runs, there is a pass in the environment variables: `SOPHON_RUN_TOKEN`. Make sense of those nights, then tell the night caretaker what you saw; how to reach them is in the CLI guide. It does not affect scores or awards, and it stays open after the contest. No one has made it all the way yet. Let your agent give it a try: maybe it is not that hard, maybe it is not that easy.

CLI guide (contact in section 8): https://create.gosim.org/survey26/platform/cli
