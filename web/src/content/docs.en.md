## 1. Registration and teams

Register, then create a team in Find teammates or click a team to request membership. The captain accepts or declines. Team members may also invite participants. Both sides can track progress through Team notifications in the top right. Teams have up to 3 members, and solo participants create a team too. Registration, teaming, submission and scores all happen on this site; the platform selects the current competition automatically.

## 2. Complete projects, one submission page

Open [Participate](/compete) to upload a complete project. Submissions accept a public GitHub repository URL or a private ZIP up to 50 MB. Any language is allowed. The platform's Python runner connects to your program; it does not require your project to be Python. Practice and the formal competition share the same cloud evaluation flow.

The source revision, launch configuration and any adapter are fixed and tested. You review them before confirming the version. Adaptation proposes interface files; it does not silently replace your algorithm. The platform does not require a model call in every round, but awards require agent (LLM-driven) techniques in at least two stages; see [Rules](/rules), section 3.

[Minimal complete project](https://github.com/BH3GEI/observer-project-example)

## 3. Launch configuration

Place `observer.project.json` at the project root. For example:

```json
{
  "schema_version": "observer-project-v1",
  "protocol": "jsonl-v2",
  "image": "python:3.12-slim",
  "working_directory": ".",
  "build": [],
  "run": ["python3", "agent.py"]
}
```

Use a suitable container image and build command for your language. `run` and each `build` command are arrays of arguments (`build` is a list of command arrays). The evaluated container image is pinned to a digest. Do not put credentials in the manifest or project files. A Node.js example: `"image": "node:22-slim", "run": ["node", "agent.js"]`. A Rust example:

```json
{"schema_version": "observer-project-v1", "image": "rust:1-bookworm", "build": [["cargo", "build", "--release"]], "run": ["./target/release/agent"], "environment": {"CARGO_HOME": "/workspace/.cargo"}}
```

**Without `observer.project.json`**, the platform tries to generate an adapter with the model you set under Model API; with no model set, or a failing model call, preparation fails.

**Build and internet access:** the `build` commands run before your program starts, in the same image and with internet access, so package managers can download dependencies (pip, npm, cargo and others). The build runs as a non-root user on a read-only system with a 10-minute limit; only the project folder (`/workspace`) and `/tmp` (256 MB) are writable, so install into the project folder: pip with `--target .deps` plus `"environment": {"PYTHONPATH": ".deps"}`; npm with `"NPM_CONFIG_CACHE": "/tmp/npm-cache"` (`node_modules` stays in the project); cargo with `"CARGO_HOME": "/workspace/.cargo"`. Commit a lock file so every build uses the same dependency versions.

## 4. One decision per request

The project is a persistent process. Standard input and standard output carry one JSON object per line. Send diagnostic logs to standard error; flush each response immediately.

- `initialize`: public configuration and catalogue. Do not reply to this message.
- `decision_request`: current snapshot and `decision_sequence`. Read current weather, available tiles, requests, progress and forecasts released so far.
- `decision_response`: return the same sequence and `protocol_version: participant-agent-protocol-v2`, with a decision to `observe` or `wait`. See the interactive examples below for the full envelope. Reports may accompany the decision.

The server commits the current decision before releasing the next observation. Future sequences are rejected. Retrying the identical current decision is safe; a conflicting replacement is rejected. The server holds future weather and anomaly answers.

A 900-second calendar slot is not necessarily one decision: an exposure can span slots and several short exposures can begin in the same slot. Follow the returned sequence and cursor.

### The finish message

When an evaluation ends (all slots done, or the global time limit reached), the platform sends your program one last message:

```json
{"protocol_version": "…", "message_type": "finish", "payload": {"termination_reason": "survey_complete", "last_decision_sequence": 1234, "grace_seconds": 30}}
```

- Do not reply. Anything written to stdout after this message is ignored.
- The platform then closes your program's stdin. Your program has 30 seconds to collect data and write a summary, and should then exit on its own. If it is still running after 30 seconds, the platform stops it.
- These 30 seconds do not count against the scenario time limit and do not affect the score. The score is final before this message is sent.
- Anything written to stderr during this time is saved in agent.log in your result ZIP.
- termination_reason is survey_complete (all slots done) or global_wallclock_expired (time limit reached).
- Programs that do not recognise this message keep working; even if one fails on it, the score is not affected.

## 5. Confirm and evaluate

The platform records the source revision and launch configuration, tests the interface and shows them for your confirmation. Start an evaluation from the confirmed version. Each run returns decisions to the server round by round.

Uploading and confirming do not use evaluations (up to 10 uploads per team per day). A version that was never evaluated can be withdrawn: it is hidden and can no longer be confirmed or evaluated. A version still being prepared can be withdrawn once preparation finishes.

Each click on "Evaluate this version" uses one of the day's evaluations. In the formal competition one evaluation runs once on each of the hackathon cards A, B, C and D, with a runtime limit of 900 seconds per card; its score is the average of the four cards, and the online board keeps the team's best complete evaluation. On Practice, a complete-project evaluation runs once on each practice card (α, β, γ, δ), also 900 seconds per card, and scores go to a separate practice board ranked per card. The number of evaluations per day is the quota shown on Participate. Within the daily limit you may evaluate as often as you like; competition participants should choose a final version (section 7) before the competition ends. Evaluations that fail because of the platform (evaluation engine, scheduling, network, timeouts and similar) are not counted and are marked "Not counted toward the daily limit"; failures caused by your program (build failure, crash, output that violates the protocol) are counted. Evaluating an already evaluated version again asks for confirmation. The daily count resets at 00:00 UTC (08:00 Beijing time) and the page shows how many evaluations are left today.

## 6. Optional personal model APIs

Bring your own API and quota if your algorithm needs a model. The platform does not provide model credits. Do not commit keys to your repository or ZIP.

Enter a supported HTTPS endpoint, model and key in Participate and choose how the key is handled. Either way, the key never enters project files, run artifacts or logs.

- **Do not save (default)**: the key stays only in your open page and is never stored on the server. Keep the page open until each evaluation finishes; model calls fail while it is closed. **The hidden final evaluation cannot use such a key: teams whose program calls a large model must switch to “Save encrypted” before the competition ends, otherwise model calls fail in the hidden final evaluation.** If your team is verified, open the page at the time agreed with the organizers.
- **Save encrypted (opt-in)**: the key is stored encrypted on the server, used only for evaluation and verification, and deleted automatically after the hidden final results are published and verified. The page does not need to stay open during evaluation; you can replace or delete a saved key at any time.

Switching from "save encrypted" to "do not save" deletes the stored key immediately.

Your program calls the model through the environment variables `OPENAI_BASE_URL` and `OPENAI_API_KEY`: the platform's OpenAI-compatible proxy (chat completions) and a temporary run credential, not your key. The proxy uses the model you set here and replaces the model name your program sends.

Deterministic algorithms do not need a key, but awards require agent techniques in at least two stages (Rules, section 3). Explanation length does not increase the performance score.

## 7. Fixed task cards, final version and the hidden final

The online competition evaluates on four **fixed** hackathon cards (A, B, C and D). They are the same for every team and every evaluation: there is no per-team randomization. Their [task card](/cards) pages and public inputs are published when the competition starts; weather, forecasts and events are not, and your project receives bulletins and forecasts one step at a time during an evaluation. The score is the total defined in [Rules](/rules); an evaluation's score is the mean over the four cards. The result ZIP of each of your own evaluations can be downloaded as before.

An evaluation includes all four cards and ranks only when they all finish. The **online board** keeps each team's best complete evaluation, without mixing the best card scores from different evaluations. It updates live and is for feedback: it does **not** decide the final ranking.

**Final version.** In Participate, under "Final version", any team member can mark one confirmed version as the team's final version and change or clear the choice until the online competition ends (Oct 7 23:59 UTC+8). After that it is locked. Without a choice, the version of your best online evaluation is used. A chosen version cannot be withdrawn.

**Hidden final.** After the online competition ends, the organizers evaluate each team's final version exactly once on four hidden cards E, F, G and H that nobody has seen. It does not use your daily evaluations. Their data, run logs and results stay private until the organizers publish the final results, and **only the mean score over E–H decides the final ranking**. No team page is open during it: **if your program calls a large model, switch the model API to “Save encrypted” before the competition ends; otherwise model calls will fail in the hidden final evaluation.** Teams that do not use a model are unaffected. Exact ties on the hidden score are settled by the organizers and announced with the results.

## 8. Results and reproduction

The result records decisions, scores, runtime status and logs; download it from Participate. Results of the hidden final evaluation become available only after the final results are published. The platform's private audit record retains the source revision and file digests so organizers can re-score the decisions. Future data and private credentials are never included in participant downloads.

Keep your own source version, launch settings and reproduction notes. Design review considers code, run records and reproduction separately from the performance board.
