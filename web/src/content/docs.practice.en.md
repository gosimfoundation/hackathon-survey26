## 1. Current competition

The current competition is Playground. Run an algorithm, upload results and inspect your score. The platform chooses the competition automatically. The formal competition (October 5–7, Beijing time) evaluates complete projects only; no CSV.

## 2. Registration and teams

Register, then create a team in Find teammates or click a team to request membership. The captain accepts or declines. Team members may also invite participants. Both sides can track progress through Team notifications in the top right. Teams have up to 3 members.

## 3. Run the starter kit

Download and extract the kit from [Resources](/resources). Double-click `run_baseline`, or run:

```sh
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 600 --out run_output
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_output/decisions.csv
```

Use `scenarios/demo-week` for a shorter demonstration. Edit `choose_action(candidates, snapshot, memory)` in `agent/my_strategy.py`, rerun and compare scores. Any implementation language is allowed. Custom programs exchange JSON messages over standard input/output following the kit's protocol; write ordinary logs to standard error.

Model calls are optional. The deterministic baseline needs no key. Never put model credentials in results or public code.

## 4. Submit and inspect results

Open [Submit](/compete), choose the scenario you used locally and upload `run_output/decisions.csv`. Maximum file size is 20 MB. Each team can submit up to 50 times per day, subject to the displayed quota.

The columns are `decision_id, slot_id, action, tile_id, program, request_id, reason`. After submission, inspect evaluation status, score components, completion and replay. Each scenario has separate standings using the team's best score.

To try the evaluation flow early, choose Submit a complete project on Participate and submit a GitHub repository or ZIP. The platform runs your program round by round in the cloud (same evaluation flow as the competition) on the public scenarios dev-fortnight and dev-reference, with a runtime limit of 5 hours per scenario. Each team gets 5 evaluations per day (reset at 00:00 UTC, 08:00 Beijing time; evaluations that fail because of the platform are not counted), model calls use the team's own model API key only, and scores go to a separate complete-project board. Use this track around the October 2–3 trainings to go through the flow once.

### Complete-project launch file (any language)

The project root must contain `observer.project.json`, which tells the platform the image, build and run commands. ZIPs made by the starter kit's `pack_agent.py` include it. **Without it**, the platform tries to generate an adapter with the model you set under Model API; with no model set, or a failing model call, preparation fails.

```json
{"schema_version": "observer-project-v1", "image": "python:3.12-slim", "run": ["python3", "-u", "agent.py"]}
```

Node.js: `"image": "node:22-slim", "run": ["node", "agent.js"]`. Rust: `"image": "rust:1-bookworm", "build": [["cargo", "build", "--release"]], "run": ["./target/release/agent"]` (`build` is a list of command arrays). The program reads one JSON message per line on stdin and writes one answer per line on stdout (protocol in the kit's `SKILL.md`); write logs to stderr, they appear as `agent.log` in the result ZIP.

## 5. Data and scoring

`config/` contains rules. `outputs/reference/` contains tiles, targets, calendar, slots, weather, forecasts, events and requests. Public files are downloadable from Resources. Current practice scenarios retain the original `participant-agent-protocol-v1` contract; existing scores and replays are preserved.

Snapshots expose available candidates, weather and progress. `observe` exposes a tile; `wait` advances time. The platform and kit use the same scorer. See [Rules](/rules) for science points, program bonuses, request rewards and penalties; the published scorer and scenario configuration define the exact formulas and constants.

## 6. Troubleshooting

Read `agent.log` after a program error. Check the scenario, CSV columns, file size and daily quota. The scoring command above independently reproduces the score. The kit's `SKILL.md`, `QUICKSTART.md` and `README.md` contain full command and field references.
