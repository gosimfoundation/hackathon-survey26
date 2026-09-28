<!--
Playground task card alpha (v4, English). Filled from taskcard.template.v4.en.md.
Still to fill from the card generator's describe output before publishing: {{START_DATE}}, {{END_DATE}},
{{NIGHTS}}, {{TARGETS}}, {{AREA_DEG2}}, {{COMPONENTS}}, {{REQUIRED}}. Then delete this comment.
-->

# Task card α (alpha): First light

A season to learn the rules. It has the usual hidden weather and no extra messages.

## At a glance

| | |
|---|---|
| Site | Paranal, Chile (virtual). Latitude −24.62°, longitude −70.40°. |
| Survey | {{START_DATE}} to {{END_DATE}}, {{NIGHTS}} nights. You observe when the sun is below −18°. |
| Targets | {{TARGETS}} targets on {{AREA_DEG2}} deg² of sky, in {{COMPONENTS}} regions. {{REQUIRED}} are required. |
| Instrument | 16 square fibres in a 4 × 4 grid. The field is 2.73° across. |
| Time limit | 900 s of wall-clock time for the whole survey. |
| Weather | Hidden. You get a short bulletin every 15 minutes and a forecast about once a week. |
| Extra messages | None. Only bulletins and forecasts. |

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
- the time you have left.

## What your agent sends

One action per decision:

| Action | Meaning |
|---|---|
| `observe` | Point the telescope, put up to 16 targets on fibres, expose for 60–3600 s, and declare a program (DARK, BRIGHT or BACKUP). |
| `wait` | Let time pass: a number of seconds, or until a given time (for example the next night). |
| `report` | Say that the instrument is faulty now. Right: +100. Wrong: −150. |
| `finish` | End the survey now. |

## How the score works

- A target scores only if it lands on the glass of the fibre you gave it, and stays above 30° altitude.
- Its score grows with brightness, exposure time and sky quality, up to a cap.
- A matching program adds 20% (DARK), 12% (BRIGHT) or 6% (BACKUP). A wrong program adds nothing.
- Only the best exposure of each target counts.
- Final score = sum of best scores − 50 × missing required targets − unevenness penalty ± reports.

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

## Try it

1. Download the v4 starter kit and card α from the Resources page. Put the card folder into the kit's `cards/` folder.
2. Run `python3 local_runner.py --card cards/alpha`. The last line shows your score.
3. Compare with `python3 local_runner.py --card cards/alpha --agent examples/idle_agent.py` (an agent that does nothing).
4. Change `agent/planner.py`, run again, and compare.
5. Pack with `python3 pack_agent.py --out ../my-agent.zip` and submit it on Participate. The Playground runs card α in the cloud, with the same 900 s limit. Daily limits are on the Rules page.

Playground scores are for practice. They do not decide awards.
