No command line required, and nothing to install beyond Python. Follow this once and you should have a score on the leaderboard in about twenty minutes.

The whole thing is three moves: **run it → change one function → upload**.

## Step 1 · Create an account

Click **Register** in the top right, fill in your name, email and a password, tick the rules checkbox, and press **Create account →**.

**No confirmation email to click** — you land straight in your dashboard. GitHub username and affiliation are optional; you can add them later under Profile.

## Step 2 · Create a team

The dashboard will tell you that you are not on a team yet. Click **Team →**, pick a name, press **Create team →**.

**Create a team even if you are competing alone** — scores are recorded per team. You get an invite code (something like `E3SE6NE9`); teammates enter it on the Team page to join, up to three people.

## Step 3 · Download the starter kit and run it

There is a **Download starter kit ↓** button on your dashboard (also on the Resources page). Unzip it and you get an `agent-observer-starter-kit` folder.

Open the folder and double-click the file for your machine:

| Your machine | Double-click |
|---|---|
| macOS | `run_baseline.command` (the system Python is enough; if it refuses to open, right-click → **Open**) |
| Windows | `run_baseline.bat` (first install Python 3.12 from [python.org](https://www.python.org/downloads/) and **tick "Add python.exe to PATH"**) |
| Linux | run `./run_baseline.sh` in a terminal |

After about fifteen seconds a page opens in your browser: that is the baseline agent's replay over 180 observing nights. The last block in the terminal is the score — the baseline lands around **12287**, and `termination_reason` should read `survey_complete`.

> **For a faster first look**, replace `run_baseline` with `run_demo_week` in the filename: a seven-night demo that finishes in about two seconds, with a replay short enough to read night by night.

## Step 4 · Change one function

Open `agent/my_strategy.py`. **The only thing you need to change all competition is the `choose_action` function in this file.**

What it does:

- the platform hands you the candidates observable in this slot, already ranked, with the highest estimated value first;
- you return the one to observe, or `None` to wait out the slot.

The file already contains several ideas you can enable by uncommenting: prioritise REQUIRED tiles, answer observation requests first, wait when conditions are poor, use `memory` to track what you have already done. The fields each candidate carries are documented at the top of the file.

Save, double-click `run_baseline` again, and see whether the score went up. If it crashes, the terminal prints the last lines of `agent.log` for you.

## Step 5 · Upload

Back on the site, open **Submit**, pick the phase and the scenario, drag in the `run_output/decisions.csv` your local run produced, and press **Upload and queue →**. Scored within seconds.

This upload flow is for practice. The competition accepts complete projects only: submit a public repository or private ZIP on the Participate page, and the platform evaluates it step by step on three fixed formal scenarios; future weather stays private. After the competition, each team's chosen final version is evaluated once on a hidden scenario, and only that score decides the ranking.

To try the evaluation flow early, choose Submit a complete project on Participate. The platform runs your program round by round in the cloud (same evaluation flow as the competition) on scenarios generated from Playground data: 5 evaluations per team per day, your own model key only, and a separate board. We recommend doing this once during the October 1–4 training.

## Step 6 · Read the result

After uploading you see your queue position and evaluation progress; a score usually arrives within a minute or two. Open the submission to find:

- **Score breakdown** — base science, program bonus, request reward, and each penalty separately
- **Night-by-night replay** — what actually got observed, which tiles completed and which never made it

The leaderboard lives under **Leaderboard** in the top navigation and updates live.

<!-- mechanics:start -->
## Extra credit · Want the finals points? Learn to catch anomalies

The competition scenarios hide three kinds of anomaly: tiles with hidden tags (nova ×1.5, reddening ×0.8 on realized score), one unannounced instrument fault (a region's efficiency collapses), plus slight nightly efficiency jitter. Finding and reporting them earns points, crying wolf costs points — this is where the finals separate the field. Practice has none of it.

To rehearse, double-click **`run_finals_preview`** in the kit (same usage as above). It finishes in about a second at a baseline of **~8214**; open the replay and `decisions.csv` to see the sample agent's own `report_instrument_failure` row. To teach your strategy the same trick, start from the worked example in `agent/anomaly_detection.py` — the snapshot's `tile_last_finished` (the realized score of your last exposure) is where every clue begins.

Details live in the Brief's finals-mechanics section and on the Rules page.

<!-- mechanics:end -->
## Stuck?

| Situation | What to do |
|---|---|
| Double-click does nothing / Python not found | On Windows install Python 3.12 with "Add to PATH" ticked; on macOS right-click → **Open** |
| Submission sits in the queue | Normal — the evaluator works through submissions one at a time; large scenarios take a while |
| Submission immediately goes `invalid` | Usually the wrong file. Upload the `run_output/decisions.csv` your local run produced, for the same scenario you ran |
| Want more weather to test against locally | `python3 make_scenario.py --out scenarios/mine --seed 7 --days 30`, then `python3 local_runner.py --scenario scenarios/mine --agent agent/minimal_agent.py` |
| Want an LLM in the loop | Copy `agent/.env.example` to `agent/.env`, fill in your own key (the platform provides no model credits), run locally, and upload the `decisions.csv` as usual |

Data formats, the protocol and the scoring formula are on the **Docs** page; `README.md` inside the kit is the full engineer's version.

Anything else, check the **FAQ**, or find the organizers' contact on the **Announcements** page.
