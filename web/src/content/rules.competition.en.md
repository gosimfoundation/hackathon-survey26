## 1. Eligibility and teams

1. Participation is open worldwide to individuals and teams. One account per person.
2. A team has 1 to 3 members. A person belongs to at most one team. Submissions are made on behalf of a team.
3. Organizers, evaluation-platform maintainers, and their immediate collaborators are excluded from awards. Their teams are marked hidden on the boards.
4. Team names and content must follow the code of conduct (section 8).
5. The competition accepts at most 150 teams (hidden organizer and test teams do not count). Once that number is reached, team registration closes automatically and no new team can be created. Individual accounts can still sign up and join an existing team that has room, using its invite code.

## 2. Schedule

All participants use the same Participate page; the platform selects the active competition.

| Stage | Time (UTC+8) | What happens |
|---|---|---|
| Competition | Oct 5 00:00 – Oct 7 23:59 | Submit and evaluate projects on the three formal scenarios A, B and C; the online board updates live; choose your final version |
| Hidden final evaluation | After Oct 7 23:59 | Organizers evaluate each team's final version once on one hidden scenario |
| Verification and results | After the hidden evaluation | Organizers verify the top teams, then publish the final standings (hidden-scenario scores only) |
| Awards Day | Oct 17 | GOSIM Shenzhen |

## 3. What you submit

1. Submit a complete project from a public GitHub repository or a private ZIP up to 50 MB. Any language is allowed. Review and confirm the fixed source revision, launch settings and proposed adapter after the platform checks them.
2. Formal competition accepts complete projects only. CSV files and local CSV sessions are not accepted.
3. Each evaluation receives current observations one round at a time. The server records each decision before releasing the next observation. Future weather and hidden anomaly answers remain private.
4. Every team has the same daily quota of complete batches, shown on the page and reset at 00:00 UTC. Within that quota you may evaluate freely. Every batch covers all three formal scenarios (A, B and C). Batches that fail because of the platform do not count toward the quota; failures caused by the project itself (build failure, crash, output that violates the protocol) do.
5. **Final version.** During the competition, any team member can mark one of the team's confirmed (and not withdrawn) versions as the team's **final version** on the Participate page, and change or clear that choice until the competition ends (Oct 7 23:59 UTC+8). The choice is then locked. If a team never chooses, the version of its best-scoring evaluation on the online board is used. A chosen final version cannot be withdrawn.
6. **Agent technology requirement.** To qualify, a project must use agent technology (driven by a large language model) in at least two of these stages: natural-language understanding, data parsing, task planning, action decision-making, tool calling, and plan adaptation. The organizers decide this mainly from an analysis of the final version's code by Claude. The platform does not require a model call in every evaluation round (section 4), but projects that do not meet this requirement are not eligible for awards.

## 4. Execution and model APIs

1. Python is the platform runner, not a language restriction. The confirmed project runs in its specified container.
2. Model calls are optional. Participants provide their own API and quota; organizer model credits are not provided. Any provider works: the API must be OpenAI-compatible and its address a public https:// address on the default port (443), not an IP address or an internal address. Keys are submitted over HTTPS and never written to projects, run records or logs. Do not place keys in project sources. You choose how your key is handled:
   - **Do not save (default)**: the key stays only in your open Participate page and is never stored on the server. Keep that page open until every evaluation finishes; model calls fail while it is closed. **The hidden final evaluation cannot use a key that is not saved: if your program calls a large model, you must switch to “Save encrypted” before the competition (the online phase) ends, otherwise its model calls will fail in the hidden final evaluation.** If your team is verified, open the page at the agreed time during verification.
   - **Save encrypted (opt-in)**: the key is stored encrypted on the server, used only for evaluation and verification, and deleted automatically once the competition has ended and the results have been verified. The page does not need to stay open during evaluation.
   You can change this choice at any time; switching from "save encrypted" to "do not save" deletes the stored key immediately.
3. External compute and external services are allowed, including your own model APIs and servers. The platform container limits (2 CPU cores, 2 GB memory) apply only to the part that runs on the platform.
4. Every decision must be made automatically by your program. Human participation in, or substitution for, decisions is prohibited.
5. Attempts to read other teams' data, tamper with scoring or deliberately exhaust platform resources can lead to disqualification.

For model calls, enter a supported HTTPS endpoint, model and key in Participate and choose "save encrypted" or "do not save" (item 2). You can replace or delete a saved key at any time.

## 5. Scoring

The score is computed by the published `scoring_core.py` (schema `challenge-score-v3`) with the constants in `config/score_config.json`. In summary:

1. Time is a calendar of 900-second slots over real nights. `observe` runs from the cursor for the tile's `nominal_exptime_seconds`, may cross slots and is split into segments; `wait` consumes the rest of the current slot.
2. For each segment of a **completed** exposure, at the segment midpoint:
   `A = min(instrument_efficiency · transparency · sky_quality / (seeing_arcsec · airmass), 3.0)`, `combined = A · lunar_quality_factor`,
   `base = V_tile · (segment_seconds / nominal_exptime_seconds) · combined`, where `V_tile` is the sum of `science_weight` over the tile's targets;
   `bonus = base · B[program]` with `B = {DARK 0.25, BRIGHT 0.15, BACKUP 0.08}`, paid only when the decision program equals the band implied by `combined` (DARK ≥ 0.65, BRIGHT ≥ 0.40, else BACKUP).
3. `total = base_science + program_bonus + request_reward + report_reward + coverage_bonus − unsafe_observation − invalid_action − avoidable_wait − required_miss − flexible_shortfall − request_miss − fault_misreport − wrong_tag_report`, with 2000 per unsafe observation (observing into a closed dome), 100 per invalid action (unknown tile/slot/program, outside the availability window, bad request tag, exposure that cannot finish before the tile sets or the night ends, stale decision), 0.001 per avoidable waiting second, 1000 per uncompleted REQUIRED tile, 100 per FLEXIBLE tile below the quota of 4 per region, and 190 per required tile of an expired request (140 rewarded per required tile when completed).
4. **Repeat observations and anomaly reports**: re-observation is legal — a tile banks the maximum over its observations (a worse repeat never lowers it), and completion still banks on the first legal observation. Scenarios hide per-tile tags (nova ×1.5, reddening ×0.8, applied silently by the scorer) and region-scoped instrument faults (a sharp efficiency collapse that is never forecast). A `decision_response` may carry a `reports` array: tag reports settle at final scoring, first report per (tile, tag), +100 correct / −150 wrong; a correct fault report publishes the fault status one simulated day later and completes the repair after two, while a misreport gets one free allowance per correct report and costs 100 each beyond it. See the `reporting` / `anomaly_tags` / `fault_response` sections of `score_config.json`.
5. **Coverage evenness** (`coverage_bonus`): `coverage_bonus = W · base_science · E`, where `E` is how evenly the finished tiles are spread over the regions (Jain's fairness index, `(Σx)² / (n·Σx²)`: 1.0 when all eight regions get the same number, 1/8 when one region takes everything). The weight `W` lives in each scenario's `config/score_config.json`: **0.35 for the current competition scenarios**. A wide survey needs even coverage to support its statistics, so crowding the easy regions now costs something.
6. Only completed exposures score. An exposure interrupted by closed weather earns nothing and is not penalised; an exposure interrupted by geometry or the end of the night earns nothing and is an invalid action.
7. Terminal penalties are applied to every run, including runs cut short by the wall clock or an agent error. An expired request with fewer feasible opportunities than required tiles is excused.
8. Completion (completed tiles ÷ tiles) and the FLEXIBLE shortfall per region are reported on the board; they are part of the score through the terminal penalties.
9. Each competition batch covers every formal scenario. Its score is the arithmetic mean of all scenario scores from that batch; it ranks on the online board only when all scenarios are complete. The board keeps each team's best complete batch, without combining scenario maxima from different batches.
10. **Fixed scenarios and sequential decisions.** The three formal scenarios A, B and C are fixed and identical for every team: every evaluation of every team plays the same scenarios, with no per-team randomization. Their files, weather, forecasts and events are not published; observations arrive one step at a time during an evaluation. The platform records each decision before releasing the next observation; future rounds cannot be submitted early and accepted decisions cannot be replaced. Future weather and hidden anomaly answers stay private. The result ZIP of each of your own evaluations remains downloadable.
11. **Hidden final scenario.** After the competition ends, organizers evaluate each team's final version (section 3, item 5) exactly once on one hidden scenario that no participant has seen, outside the daily quota. The hidden scenario, its per-step data, run logs and results stay private until the organizers publish the final results. Only this hidden score decides the final ranking; the online board does not.

## 6. Ranking, ties, and verification

1. **Final ranking**: only the hidden-scenario score of each team's final version (section 5, item 11) counts, by score, descending. Ties on the hidden score are settled by the organizers and announced with the results.
2. **Online board**: during the competition it ranks each team's best batch (section 5, item 9), live; on an exact tie the earlier batch ranks first. It is for feedback only and does not decide awards. Organizers may freeze it during the final hours.
3. The organizers run the hidden final evaluation after the online phase freezes, with no team page open. Teams whose program calls a large model must switch their model API to “Save encrypted” (section 4, item 2) before the competition (the online phase) ends; for teams still on “Do not save”, model calls fail in the hidden final evaluation, at their own risk. Teams that do not use a model are unaffected. Saved keys are deleted automatically after the hidden final results are verified and published.
4. Before awards are confirmed, organizers verify the top teams: they may re-run the final version, and may ask for the complete code, the versions and configuration of the external services and models used, and the call records from evaluation. Keep those external services and your saved key available until verification ends; teams that chose not to save their key must open the Participate page at the agreed time during verification. Results that cannot run, that are clearly inconsistent with the ranked score, or that involved human intervention are removed.
5. Organizers may re-score submissions if a scorer defect is found. Any change to the scorer or the constants is announced with a version number and applies to every submission of the phase. The current constants are provisional organizer calibration values until the online competition opens.

## 7. Awards

| Award | Prize | Count |
|---|---|---|
| First Prize | $2,000 | 1 |
| Second Prize | $1,000 | 2 |
| Third Prize | $500 | 3 |

Amounts are gross. Winning teams are invited to Awards Day at GOSIM Shenzhen on October 17, 2026; attendance is not required to receive a prize.

Design evaluation is separate from the performance board. It considers code, run
records and reproducibility, not explanation length. Participants can save
architecture and reproduction notes on the Participate page. Design-award places and
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
