## 1. Register and join a team

Register an account, then open **Find teammates**. Create your own team, or click a team to send a join request. Its captain accepts or declines. You can also accept an invitation through the notification bell in the top right. Teams have up to three members; solo participants also need a team.

## 2. Prepare a complete project

Your project may use any language. It reads current observations and returns one decision at a time. The platform does not require a model call in every round, but awards require agent (LLM-driven) techniques in at least two of: natural-language understanding, data parsing, task planning, action decision-making, tool calling and plan adaptation; see [Rules](/rules). See [Docs](/docs) for the interface and an example project; in the starter kit, `python3 pack_agent.py` builds an uploadable ZIP.

## 3. Submit your project

The prominent **Submit** button opens the single [Participate](/compete) workspace. Enter a public repository link or upload a private ZIP. Review the source version, launch settings and proposed interface files, then confirm the version to evaluate. CSV uploads are not accepted.

The platform provides no model credit; bring your own API and quota. Never place keys in the project.

For model calls, enter a supported HTTPS endpoint, model and key in Participate and choose how the key is handled:

- **Do not save (default)**: the key stays only in the page; keep the page open until each evaluation finishes. **The hidden final evaluation cannot use it: if your program calls a large model, switch to “Save encrypted” before the competition ends, otherwise model calls fail in the hidden final evaluation.** If your team is verified as a top team, you must also open the page at the agreed time during verification.
- **Save encrypted (opt-in)**: the key is stored encrypted on the server and deleted automatically after the hidden final results are published and verified; the page does not need to stay open during evaluation.

## 4. Evaluate and review

Each batch covers the three fixed formal scenarios (A, B and C), the same for every team. Scenario files, weather, forecasts and events are not published; observations arrive one step at a time. Each team has 10 batches per day, reset at 00:00 UTC (08:00 Beijing time), with a runtime limit of 3600 seconds per scenario; batches that fail because of the platform are not counted. The platform records each decision before releasing the next observation.

Your result includes the score, its components and the run record. All scenarios must finish before the batch appears on the online board, which shows your team's best complete batch. That board is live feedback only.

Use the result downloads (including `agent.log`) to inspect the decisions and failures. Contact the organizers through [Announcements](/announcements) if an evaluation cannot complete.

## 5. Choose your final version

Under **Final version** in Participate, mark one confirmed version as your team's final version. You can change or clear it until the competition ends (Oct 7 23:59 UTC+8); without a choice, the version of your best online batch is used. After the competition, the organizers evaluate each team's final version once on one hidden scenario. **Only that hidden score decides the final ranking.** Its results stay private until the organizers publish them.
