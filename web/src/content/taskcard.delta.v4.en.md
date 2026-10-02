# Task card δ (delta): The long year

A whole year with a hundred fibres, and part of your recent data can be lost once.

## At a glance

| | |
|---|---|
| Site | Nemo Observatory, South Pacific (fictional). Latitude −45.00°, longitude −135.00°. |
| Survey | 2027-01-01 to 2027-12-31, 365 nights. You observe when the sun is below −18°. |
| Targets | 30,000 targets on 6,000 deg² of sky, in 3 regions. 1,500 are required. |
| Instrument | 100 contiguous fibre assignment cells in a 10 × 10 grid. The field covers 6 deg² and is about 2.45° across. |
| Time limit | 900 s of wall-clock time for the whole survey. |
| Weather | The full weather and event files of this card are public (Resources page). Your agent does not get them: during a run it only receives a short bulletin every 15 minutes and a forecast about once a week. |
| Extra messages | Time-limited observation requests (`observation_request`) and their results (`observation_request_result`). Possibly one `state_resync` message. It means part of your recent data was lost. It lists the targets that still count and their best scores. Rebuild your list of finished targets from it. The time already spent is not returned. |

## Your goal

1. Observe as many valuable targets as you can, as well as you can.
2. Observe every **required** target well enough. Each one you miss costs 50 points.
3. Spread your work across the sky. Leaving parts of the sky empty costs up to 200 points.

## What your agent gets

**Once, at the start (`initialize`):**
- the site, the list of nights and when each night starts and ends;
- every target: position, class, brightness, weight and whether it is required;
- the sky regions, the instrument layout and the full score settings;
- the time limit.

**At every decision (`decision_request`):**
- the current time;
- the latest bulletin and forecast, and all messages since your last decision;
- the result of your last observation: which targets hit their fibre, and their scores;
- the time-limited observation requests in progress and how far along they are (`active_requests`);
- the time you have left.

## What your agent sends

One action per decision:

| Action | Meaning |
|---|---|
| `observe` | Point the telescope, put up to 100 targets on fibres, expose for 60–3600 s, and declare a program (DARK, BRIGHT or BACKUP). |
| `wait` | Let time pass: a number of seconds, or until a given time (for example the next night). |
| `report` | Say that the instrument is faulty now. Right: +100. After each correct report, wrong reports are free up to the card's configured allowance, then −150 each; consecutive report actions have a separate cap. |
| `finish` | End the survey now. |

## How the score works

- A target scores only if it falls in its assigned fibre's cell and stays at or above 30° altitude.
- Its score grows with brightness, exposure time and sky quality, up to a cap.
- A matching program adds 20% (DARK), 12% (BRIGHT) or 6% (BACKUP). A wrong program adds nothing.
- Only the best exposure of each target counts.
- Time-limited observation requests: complete enough of a request's targets inside its time window to earn its reward; a missed request costs nothing.
- Final score = sum of best scores − 50 × missing required targets − unevenness penalty ± reports + request rewards.

**Example.** A target has brightness 0.60 and weight 1.0. You expose it for 900 s. The sky quality is 0.75.
Its factor is 0.60 × 900 × 0.75 ÷ 450 = 0.90. You declared DARK and the sky was DARK, so the score is
1.0 × 0.90 × 1.20 = **1.08**. With a 300 s exposure the factor is only 0.30. A required target needs at
least 0.50, so it would still count as missing.

## Common mistakes

- Printing logs to stdout. Only JSON answers go to stdout. Logs go to stderr.
- Answering with the wrong `decision_sequence`, or adding unknown fields. The run stops with `agent_error`.
- Calling a language model on every decision. The time limit runs out long before the survey ends.
- Short exposures on faint targets. Exposures do not add up; only the best one counts.
- Pointing low in a direction a bulletin warns about.
- Reporting a fault after one bad exposure. Weather also lowers scores.
- Reading the weather files from your agent. On the platform your agent only has its own folder.

## Try it

1. Download the v4 starter kit and card δ from the Resources page. Put the card folder into the kit's `cards/` folder.
2. Run `python3 local_runner.py --card cards/delta`. The last line shows your score. The weather files are public, so the same decisions give the same score here and on the platform.
3. Compare with `python3 local_runner.py --card cards/delta --agent examples/idle_agent.py` (an agent that does nothing).
4. Change `agent/planner.py`, run again, and compare.
5. Pack with `python3 pack_agent.py --out ../my-agent.zip` and submit it on Participate. Practice runs all practice cards α, β, γ and δ in the cloud, with the same 900 s limit. Daily limits are on the Rules page.

Practice scores do not decide awards.
