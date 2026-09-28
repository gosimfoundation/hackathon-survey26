<!--
v4 task card template (English). One page per card. Copy it, fill every {{...}} field from the card
generator's describe output, and delete this comment. Keep sentences short: one idea per sentence.
Stage words: a card page must use only its own stage's words (see tests/test_v4_participant_docs.py).
Never add hidden-truth details: no seeds, no event times or strengths, no instrument-fault details.
-->

# Task card {{CARD_ID}}: {{CARD_TITLE}}

{{ONE_SENTENCE_STORY}}

## At a glance

| | |
|---|---|
| Site | Paranal, Chile (virtual). Latitude −24.62°, longitude −70.40°. |
| Survey | {{START_DATE}} to {{END_DATE}}, {{NIGHTS}} nights. You observe when the sun is below −18°. |
| Targets | {{TARGETS}} targets on {{AREA_DEG2}} deg² of sky, in {{COMPONENTS}} regions. {{REQUIRED}} are required. |
| Instrument | 16 square fibres in a 4 × 4 grid. The field is 2.73° across. |
| Time limit | {{WALLCLOCK}} s of wall-clock time for the whole survey. |
| Weather | Hidden. You get a short bulletin every 15 minutes and a forecast about once a week. |
| Extra messages | {{EXTRA_MESSAGES}} |

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

{{TRY_IT}}
