## 1. Playground

The current competition is Playground. Register, form a team, submit and view scores here. The platform selects the current competition for you.

1. One account per person and one team per person. Teams have up to 3 members. Solo participants also create a team.
2. Click a team in Find teammates to request membership. Its captain can accept or decline. Team members can invite participants, who can accept or decline the invitation.
3. Team notifications in the top right show sent and received requests, invitations and their progress. Invitation codes and links still work.
4. Organizers, platform maintainers and their immediate collaborators may practice but are excluded from awards and hidden on public standings.

## 2. Submission

1. Run your algorithm locally and upload its `decisions.csv` through Submit. Any language or algorithm is allowed, and practice runs need no model call. Note that awards require agent (LLM-driven) techniques in at least two of these stages: natural-language understanding, data parsing, task planning, action decisions, tool calling and plan adaptation. It is worth preparing for this now.
2. Required columns: `decision_id, slot_id, action, tile_id, program, request_id, reason`. Maximum file size: 20 MB.
3. Each team may submit up to 50 times per day, subject to the displayed quota. Select the same scenario used locally; no competition-stage selection is needed.
4. The starter kit includes public scenarios, example strategies, the runner, scorer and replay tools. Never include model credentials in a submitted file.
5. You can also submit a complete project (public GitHub repository or ZIP) on Participate: the "Playground · complete projects" track. The platform runs it round by round in the cloud (same evaluation flow as the competition) on the public scenarios dev-fortnight and dev-reference, with a runtime limit of 5 hours (18000 seconds) per scenario. Each team gets 5 evaluations per day, reset at 00:00 UTC (08:00 Beijing time); evaluations that fail because of the platform are not counted. Model calls may only use the team's own model API key. Scores go to a separate complete-project board that does not decide awards. Use it around the October 2–3 trainings to go through the cloud evaluation flow once.
6. Kimi Coding Plan: each team that runs through the Playground (at least one successful score: a scored CSV submission or a scored complete-project evaluation) receives one Kimi Coding Plan code (coming soon). The captain claims it on the dashboard once organizers release the codes; every team member can see it there. Use endpoint `https://api.kimi.com/coding/v1` and model `kimi-for-coding` or `k3`. Hidden and test teams are not eligible.

## 3. Scores and standings

The platform uses the published `scoring_core.py` and each scenario's `score_config.json`. Existing rules and scores are preserved.

- `observe` exposes a tile and `wait` advances time. Slots last 900 seconds; an exposure may span slots.
- Science scores depend on tile value, completed exposure duration, weather and geometry. Matching observation programs earn a bonus.
- Completing requests earns rewards. Unsafe observations, invalid actions, avoidable waiting, missing required tiles, regional shortfalls and missed requests incur penalties.
- Only completed exposures earn science points. Weather interruptions are not penalized; geometry or night-end interruptions count as invalid actions.
- Repeated observations are allowed and each tile keeps its best score. Practice scenarios do not enable hidden anomaly reports; the additional coverage-evenness reward weight is zero.
- Scenarios have separate standings. Each team keeps its best score per scenario; exact ties favor the earlier submission. Playground standings are for practice and do not determine awards.

Submission details include score components, completion, replay and result downloads. The same scenario and official scorer reproduce a submitted CSV's score.

## 4. Conduct and privacy

Respect other participants. Do not share accounts, submit another team's work, or create extra teams to multiply quotas. Do not access another team's private data, alter scoring or deliberately exhaust resources. Report defects to the organizers.

Team names, scores and ranks are public. Registration information is used to operate the event. Participants control their public cards. Submission files and detailed results are available only to the team and organizers and kept by the organizers and may be used for academic research and publications; published material is anonymized unless the team agrees otherwise. Existing submissions, scores and replays remain available.

Award details and event updates appear in announcements. Contact: hackathon@gosim.org
