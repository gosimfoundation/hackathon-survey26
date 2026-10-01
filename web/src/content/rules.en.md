## 1. Eligibility and teams

1. Participation is open worldwide to individuals and teams. One account per person.
2. A team has 1 to 3 members. A person belongs to at most one team. Submissions are made on behalf of a team.
3. Organizers, evaluation-platform maintainers, and their immediate collaborators are excluded from awards. Their teams are marked hidden on the boards.
4. Team names and content must follow the code of conduct (section 8).
5. The competition accepts at most 150 teams (hidden organizer and test teams do not count). Once that number is reached, team registration closes automatically and no new team can be created. Individual accounts can still sign up and join an existing team that has room, using its invite code.

## 2. Schedule and task cards

All participants use the same Participate page; the platform selects the active competition. The event uses three sets of task cards. Each card is one complete simulated survey season:

| Task cards | Used for | Published |
|---|---|---|
| Practice cards α, β, γ, δ | Playground practice | Now: the card pages and every file (including the weather, forecast and event files), so scores can be reproduced locally |
| Hackathon cards A, B, C, D | Online competition evaluations and the online board | When the competition starts (Oct 5 00:00, UTC+8): the card pages and the public inputs; weather, forecasts and events stay private |
| Hidden cards E, F, G, H | The final evaluation after the deadline, which decides the final ranking | Never; participants do not see them during the event |

The fourth card of each set (δ, D, H) is an extreme card: less observable time and more disruptions. Card pages are on [Task cards](/cards); downloads are on [Resources](/resources).

| Stage | Time (UTC+8) | What happens |
|---|---|---|
| Playground practice | Open until the competition starts | Submit a complete project on the practice cards for cloud evaluation; boards are for practice only |
| Online training | Oct 2–3 | Introduces the simulator and participant protocol; details in announcements |
| Competition | Oct 5 00:00 – Oct 7 23:59 | Submit complete projects; every evaluation runs once on each of the cards A–D; the online board updates live; choose your final version |
| Hidden-card final evaluation | After Oct 7 23:59 | Organizers evaluate each team's final version once on the hidden cards E–H |
| Verification and results | After the hidden evaluation | Organizers verify the top teams, then publish the final standings (hidden-card scores only) |
| Awards Day | Oct 17 | GOSIM Shenzhen |

### Playground rules

1. Download the v4 starter kit and the practice cards, run your agent locally and check its score, then pack the agent and submit it as a complete project (public GitHub repository or ZIP) on Participate: the "Playground · complete projects" track. The platform runs it round by round in the cloud (same evaluation flow as the competition). Every evaluation runs once on each practice card, with a runtime limit of 900 seconds per card.
2. The daily number of evaluations is the quota shown in the "Phase configuration" table above and on Participate, reset at 00:00 UTC (08:00 Beijing time); evaluations that fail because of the platform are not counted. Model calls may only use the team's own model API key.
3. The Playground ranks each card separately and each team keeps its best score per card; exact ties favor the earlier submission. Practice scores do not decide awards.
4. Any language or algorithm is allowed, and practice runs need no model call. Note that awards require agent (LLM-driven) techniques in at least two of these stages: natural-language understanding, data parsing, task planning, action decisions, tool calling and plan adaptation (section 3, item 6). It is worth preparing for this now.
5. Uploading a `decisions.csv` for the earlier v3 practice scenarios remains available as a warm-up. It uses the v3 scenarios and the v3 scoring rules (see the v3 starter kit on Resources), which differ from the v4 task cards of this competition.
6. Kimi Coding Plan: each team that runs through the Playground (at least one successful score: a scored CSV submission or a scored complete-project evaluation) receives one Kimi Coding Plan code. The captain claims it on the dashboard once organizers release the codes; every team member can see it there. Use endpoint `https://api.kimi.com/coding/v1` and model `kimi-for-coding` or `k3`. Hidden and test teams are not eligible.

## 3. What you submit

1. Submit a complete project from a public GitHub repository or a private ZIP up to 50 MB. Any language is allowed. Review and confirm the fixed source revision, launch settings and proposed adapter after the platform checks them.
2. Formal competition accepts complete projects only. CSV files and local CSV sessions are not accepted.
3. Each evaluation receives current observations one round at a time: the server records each decision before releasing the next round. Future weather, events and instrument faults remain private.
4. Every team has the same daily quota. One evaluation runs once on each of the cards A, B, C and D, with a runtime limit of 900 seconds per card. The number of evaluations per team per day is the quota shown in the "Phase configuration" table above and on Participate, reset at 00:00 UTC (08:00 Beijing time). Within that quota you may evaluate freely. Evaluations that fail because of the platform do not count toward the quota; failures caused by the project itself (build failure, crash, output that violates the protocol) do.
5. **Final version.** During the competition, any team member can mark one of the team's confirmed (and not withdrawn) versions as the team's **final version** on the Participate page, and change or clear that choice until the competition ends (Oct 7 23:59 UTC+8). The choice is then locked. If a team never chooses, the version of its best online evaluation is used. A chosen final version cannot be withdrawn.
6. **Agent technology requirement.** To qualify, a project must use agent technology (driven by a large language model) in at least two of these stages: natural-language understanding, data parsing, task planning, action decision-making, tool calling, and plan adaptation. The organizers decide this mainly from an analysis of the final version's code by Claude. The platform does not require a model call in every evaluation round (section 4), but projects that do not meet this requirement are not eligible for awards.

## 4. Execution and model APIs

1. Python is the platform runner, not a language restriction. The confirmed project runs in its specified container.
2. Model calls are optional. Participants provide their own API and quota; organizer model credits are not provided. Any provider works: the API must be OpenAI-compatible and its address a public https:// address on the default port (443), not an IP address or an internal address. Keys are submitted over HTTPS and never written to projects, run records or logs. Do not place keys in project sources. You choose how your key is handled:
   - **Do not save (default)**: the key stays only in your open Participate page and is never stored on the server. Keep that page open until every evaluation finishes; model calls fail while it is closed. **The hidden final evaluation cannot use a key that is not saved: if your program calls a large model, you must switch to “Save encrypted” before the competition (the online phase) ends, otherwise its model calls will fail in the hidden final evaluation.** If your team is verified, open the page at the agreed time during verification.
   - **Save encrypted (opt-in)**: the key is stored encrypted on the server, used only for evaluation and verification, and deleted automatically after the hidden final results are published and verified. The page does not need to stay open during evaluation.
   You can change this choice at any time; switching from "save encrypted" to "do not save" deletes the stored key immediately.
3. External compute and external services are allowed, including your own model APIs and servers. The platform container limits (2 CPU cores, 2 GB memory) apply only to the part that runs on the platform.
4. Every decision must be made automatically by your program. Human participation in, or substitution for, decisions is prohibited.
5. Attempts to read other teams' data, tamper with scoring or deliberately exhaust platform resources can lead to disqualification.

For model calls, enter a supported HTTPS endpoint, model and key in Participate and choose "save encrypted" or "do not save" (item 2). You can replace or delete a saved key at any time.

## 5. Scoring

Each card is scored by the published v4 scorer (`challenge/v4_scorer.py` in the starter kit) with the parameters in that card's `config/v4_score_config.json`; the `initialize` message carries them in full. The values below are those of the current cards; the full protocol and formulas are in the v4 starter kit's `README.md` (download on [Resources](/resources)) and on the [task card](/cards) pages.

1. **Survey and actions.** Each card is one survey season; observing is possible while the sun is below −18°. At every decision the agent sends one action: `observe` (point the telescope, put up to 16 targets on fibres, expose for 60–3600 s and declare a program: DARK, BRIGHT or BACKUP), `wait`, `report` (the instrument is faulty now) or `finish`.
2. **Target score.** A target scores only if it falls in its assigned fibre's cell and stays at or above 30° altitude for the whole exposure. Factor = min(brightness × exposure seconds × sky quality ÷ 450, 1); target score = science weight × factor × program bonus.
3. **Program bonus.** When the declared program matches the target's sky band, the score is multiplied by DARK 1.20, BRIGHT 1.12 or BACKUP 1.06; otherwise by 1.00.
4. **Best exposure only.** A target may be observed again, but exposures do not add up: only its best score counts.
5. **Required targets.** Every required target that is not completed costs 50 points; completion needs a best factor of at least 0.5, and the program bonus cannot replace that threshold.
6. **Even coverage.** The completed fraction is computed per 10° right-ascension band and its evenness is measured with Jain's index J: the penalty is 200 × (1 − J), at most 200 points.
7. **Fault reports.** Instrument faults never appear in bulletins or forecasts; only exposure scores reveal them. A `report` while an unrepaired fault exists earns +100 and repairs it at once. After each correct report, wrong reports are free up to the card's configured allowance, then −150 each; consecutive report actions have a separate cap.
8. **Time-limited observation requests.** During the survey, time-limited observation requests are published on schedule (`observation_request` messages in `new_messages`; the decision snapshot's `active_requests` shows live progress). A request lists a set of targets, a minimum number to complete, a completion threshold, a reward and a deadline; valid exposures that lie wholly between its publication and its deadline count automatically, with no accept action. Reaching the minimum (judged on the completion factor, without the program bonus) earns the request's reward at the deadline; a missed request costs nothing. An `observation_request_result` is sent at the deadline, and re-sent as a correction (`revised: true`) if a data loss later voids exposures.
9. **Total** = sum of best target scores − 50 × missing required targets − evenness penalty ± fault reports + rewards of completed observation requests.
10. **Time limit.** Each card has 900 seconds of real time (counted from the first `decision_request`, including the agent's thinking and platform processing). The survey ends when the time runs out, when the agent errs (`agent_error`) or when it sends `finish`; earlier observations still score and the terminal penalties still apply.
11. **Hackathon cards A–D.** The four cards are fixed and identical for every team, with no per-team randomization. When the competition starts, their card pages and public inputs (targets, sky footprint, site, telescope and fibres, observing calendar, score settings) are published; weather, forecasts, events and instrument faults are not, and during an evaluation the agent only receives bulletins and forecasts step by step. The platform records each decision before releasing the next round; future rounds cannot be submitted early and accepted decisions cannot be replaced. The result ZIP of each of your own evaluations remains downloadable.
12. **Evaluation score and online board.** An evaluation's score is the arithmetic mean of its four card scores (A, B, C, D); it ranks on the online board only when all four cards are complete. The board keeps each team's best evaluation, without combining card maxima from different evaluations, and also shows each card's score.
13. **Hidden cards E–H.** After the competition ends, organizers evaluate each team's final version (section 3, item 5) exactly once on four hidden cards E, F, G and H that no participant has seen, also 900 seconds per card and outside the daily quota. The hidden cards, their per-step data, run logs and results stay private until the organizers publish the final results. The final score is the arithmetic mean of the four hidden card scores; the online board does not decide the final ranking.

## 6. Ranking, ties, and verification

1. **Final ranking**: only the hidden-card score (E–H) of each team's final version (section 5, item 13) counts, by score, descending. Ties on the hidden score are settled by the organizers and announced with the results.
2. **Online board**: during the competition it ranks each team's best evaluation (section 5, item 12), live; on an exact tie the earlier evaluation ranks first. It is for feedback only and does not decide awards. Organizers may freeze it during the final hours.
3. The organizers run the hidden-card final evaluation after the online phase freezes, with no team page open. Teams whose program calls a large model must switch their model API to “Save encrypted” (section 4, item 2) before the competition (the online phase) ends; for teams still on “Do not save”, model calls fail in the hidden final evaluation, at their own risk. Teams that do not use a model are unaffected. Saved keys are deleted automatically after the hidden final results are verified and published.
4. Before awards are confirmed, organizers verify the top teams: they may re-run the final version, and may ask for the complete code, the versions and configuration of the external services and models used, and the call records from evaluation. Keep those external services and your saved key available until verification ends; teams that chose not to save their key must open the Participate page at the agreed time during verification. Results that cannot run, that are clearly inconsistent with the ranked score, or that involved human intervention are removed.
5. Organizers may re-score submissions if a scorer defect is found. Any change to the scorer or its parameters is announced with a version number and applies to every submission of the phase.

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
2. Private ZIP projects, results, run records and score reports are visible only to the submitting team and organizers and are kept by the organizers and may be used for academic research and publications; published material is anonymized unless the team agrees otherwise. Forks of public repositories remain public; use ZIP for private projects. Model keys never enter project repositories or frontend code.
3. Team names, scores, and ranks are public.

Contact: hackathon@gosim.org
