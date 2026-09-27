## 1. Eligibility and teams

1. Participation is open worldwide to individuals and teams. One account per person.
2. A team has 1 to 3 members. A person belongs to at most one team. Submissions are made on behalf of a team.
3. Organizers, evaluation-platform maintainers, and their immediate collaborators may participate in the Playground phase but are excluded from awards. Their teams are marked hidden on the boards.
4. Team names and content must follow the code of conduct (section 8).

## 2. Phases

| Phase | Dates (UTC) | Submissions | Board |
|---|---|---|---|
| Practice | from registration until Awards Day | decisions.csv, 50 per team per day | informational |
| Practice · complete projects | same | complete projects, 5 evaluations per team per day | separate board, informational |
| Online Competition | 2026-10-04 16:00 to 2026-10-07 15:59 (Oct 5–7 in UTC+8) | complete projects or local-session CSVs, 10 batches per team per day | decides the awards |
| Awards Day | 2026-10-17 at GOSIM Shenzhen | none | final results announced |

The live phase configuration table above this document is authoritative if the two differ.

## 3. What you submit

1. **Practice results.** The Playground still accepts `decisions.csv` with the columns `decision_id, slot_id, action, tile_id, program, request_id, reason`, scored by the frozen scorer. Existing submissions, scores, replays and practice rankings remain unchanged. The Playground also has a complete-project track: it runs the same flow as the competition on scenarios generated from Playground data, 5 evaluations per team per day, with the team's own model key only and a separate board. Before the competition, including the October 1–4 training, use it to rehearse the competition flow.
2. **Complete competition projects.** Submit a public GitHub repository URL or a private project ZIP. Any project language is allowed; Python is only the platform runner. The platform fixes the source version, checks launch settings and runs a public preview. If adaptation is needed, a model proposes reviewable interface files that the participant must confirm before formal evaluation. Calling a model is optional.
3. **Local competition CSVs.** Start a local session on the project page, download the runner, execute your project on your computer and upload the session's exported `decisions.csv`. The server reveals current information and actual observation results step by step. The CSV must match the decisions actually executed by the server. Cloud projects use the same interface; future weather and anomaly answers are not downloadable.
4. CSV files are limited to 20 MB; project ZIPs to 50 MB. Practice scenarios retain their original `participant-agent-protocol-v1` contract. Competition scenarios use the anomaly mechanics in `participant-agent-protocol-v2`; the starter kit's `finals-preview` lets you rehearse the anomaly mechanics locally.

## 4. Running locally

1. Practice uses the starter kit's `local_runner.py`. Competition uses `project_platform.local`, downloaded from the project page, with the session instructions shown there. Any project language is allowed; Docker is the default execution environment.
2. Model calls are optional; use your own API key, set on the Participate page. The platform does not provide model credits. Do not put keys in projects or CSVs. Each scenario has a shared runtime limit and the server computes the official score.
3. Attempts to read other teams' data, to tamper with the scorer or with score files, or to exhaust platform resources deliberately lead to disqualification.

## 5. Scoring

The score is computed by the published `scoring_core.py` (schema `challenge-score-v3`) with the constants in `config/score_config.json`. In summary:

1. Time is a calendar of 900-second slots over real nights. `observe` runs from the cursor for the tile's `nominal_exptime_seconds`, may cross slots and is split into segments; `wait` consumes the rest of the current slot.
2. For each segment of a **completed** exposure, at the segment midpoint:
   `A = min(instrument_efficiency · transparency · sky_quality / (seeing_arcsec · airmass), 3.0)`, `combined = A · lunar_quality_factor`,
   `base = V_tile · (segment_seconds / nominal_exptime_seconds) · combined`, where `V_tile` is the sum of `science_weight` over the tile's targets;
   `bonus = base · B[program]` with `B = {DARK 0.25, BRIGHT 0.15, BACKUP 0.08}`, paid only when the decision program equals the band implied by `combined` (DARK ≥ 0.65, BRIGHT ≥ 0.40, else BACKUP).
3. `total = base_science + program_bonus + request_reward + report_reward + coverage_bonus − unsafe_observation − invalid_action − avoidable_wait − required_miss − flexible_shortfall − request_miss − fault_misreport − wrong_tag_report`, with 2000 per unsafe observation (observing into a closed dome), 100 per invalid action (unknown tile/slot/program, outside the availability window, bad request tag, exposure that cannot finish before the tile sets or the night ends, stale decision), 0.001 per avoidable waiting second, 1000 per uncompleted REQUIRED tile, 100 per FLEXIBLE tile below the quota of 4 per region, and 190 per required tile of an expired request (140 rewarded per required tile when completed).
4. **Repeat observations and anomaly reports**: re-observation is legal — a tile banks the maximum over its observations (a worse repeat never lowers it), and completion still banks on the first legal observation. Scenarios hide per-tile tags (nova ×1.5, reddening ×0.8, applied silently by the scorer) and region-scoped instrument faults (a sharp efficiency collapse that is never forecast). A `decision_response` may carry a `reports` array: tag reports settle at final scoring, first report per (tile, tag), +100 correct / −150 wrong; a correct fault report publishes the fault status one simulated day later and completes the repair after two, while a misreport gets one free allowance per correct report and costs 100 each beyond it. See the `reporting` / `anomaly_tags` / `fault_response` sections of `score_config.json`.
5. **Coverage evenness** (`coverage_bonus`): `coverage_bonus = W · base_science · E`, where `E` is how evenly the finished tiles are spread over the regions (Jain's fairness index, `(Σx)² / (n·Σx²)`: 1.0 when all eight regions get the same number, 1/8 when one region takes everything). The weight `W` lives in each scenario's `config/score_config.json`: **0 for the practice scenarios** (so local scores are unaffected) and **0.35 for the competition scenarios**. A wide survey needs even coverage to support its statistics, so crowding the easy regions now costs something.
6. Only completed exposures score. An exposure interrupted by closed weather earns nothing and is not penalised; an exposure interrupted by geometry or the end of the night earns nothing and is an invalid action.
7. Terminal penalties are applied to every run, including runs cut short by the wall clock or an agent error. An expired request with fewer feasible opportunities than required tiles is excused.
8. Completion (completed tiles ÷ tiles) and the FLEXIBLE shortfall per region are reported on the board; they are part of the score through the terminal penalties.
9. Each competition batch covers every competition scenario. Its score is the arithmetic mean of all scenario scores from that batch; it ranks only when all scenarios are complete. Each team keeps its best complete batch, without combining scenario maxima from different batches. Practice still ranks each scenario separately using each team's best score.
10. **Random scenarios and sequential decisions.** In competition phases with randomization enabled, each team receives one fixed private seed for weather, events and hidden tags: every evaluation of a team uses the same scenario, and different teams get different ones. Public observation tasks and scoring rules stay fixed. The platform records each decision before releasing the next observation; future rounds cannot be submitted early and accepted decisions cannot be replaced. A new evaluation attempt does not change the scenario.
11. **Difficulty calibration.** Three fixed online reference policies test each generated scenario against bounds frozen in advance; outliers are not served to participants. The ranking score is `10000 × (raw score − all-wait score) / (reference-policy mean − all-wait score)`: all-wait scores 0, the reference mean scores 10000, and stronger policies can exceed 10000. Raw totals and components remain visible. Item 9 averages the calibrated scores. Calibration reduces scenario differences without guaranteeing equal difficulty for every possible strategy. Before activation, organizers validate independent samples and freeze the generator, calibration rules and scenario configuration. Private records support regeneration and score audits. Practice and existing scores are unchanged.

## 6. Ranking, ties, and verification

1. Only scored, non-excluded submissions count, combined as in section 5, item 9. Ranking is by score, descending; on an exact tie the earlier submission ranks first.
2. The Online Competition board is live. Organizers may freeze the board during the final hours and publish the final standings after verification.
3. Before awards are confirmed, organizers may ask the top teams for their agent code and a short description of the approach, and regenerate the decisions.csv with it. Results that cannot be reproduced are removed.
4. Organizers may re-score submissions if a scorer defect is found. Any change to the scorer or the constants is announced with a version number and applies to every submission of the phase. The current constants are provisional organizer calibration values until the online competition opens.

## 7. Awards

| Award | Prize | Count |
|---|---|---|
| First Prize | $2,000 | 1 |
| Second Prize | $1,000 | 2 |
| Third Prize | $500 | 3 |

Amounts are gross. Winning teams are invited to Awards Day at GOSIM Shenzhen on October 17, 2026; attendance is not required to receive a prize.

Design evaluation is separate from the performance board. It considers code, run
records and reproducibility, not explanation length. Participants can save
architecture and reproduction notes on the project page. Design-award places and
prizes will be announced separately.

## 8. Code of conduct

1. Be respectful. Harassment, discrimination, and abusive content in team names, notes, or agent output are not tolerated.
2. Do not share accounts, do not submit another team's work, and do not create multiple teams to multiply the daily limit.
3. Report platform defects to the organizers instead of exploiting them. Reports of scorer or sandbox issues are welcome and credited.
4. Decisions of the organizers on eligibility, disqualification, and awards are final.

## 9. Data and privacy

1. Registration data (name, email, affiliation, GitHub handle) is used only to run the event and to contact winners.
2. Private ZIP projects, results, run records and score reports are visible only to the submitting team and organizers and are retained until 90 days after Awards Day. Forks of public repositories remain public; use ZIP for private projects. Model keys never enter project repositories or frontend code.
3. Team names, scores, and ranks are public.

Contact: hackathon@gosim.org
