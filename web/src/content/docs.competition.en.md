## 1. Complete projects, one submission page

Open [Participate](/compete) to upload a complete project. Submissions accept a public GitHub repository URL or a private ZIP up to 50 MB. Any language is allowed. The platform's Python runner connects to your program; it does not require your project to be Python.

The source revision, launch configuration and any adapter are fixed and tested. You review them before confirming the version. Adaptation proposes interface files; it does not silently replace your algorithm. Model calls are optional.

[Minimal complete project](https://github.com/BH3GEI/observer-project-example)

## 2. Launch configuration

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

Use a suitable container image and build command for your language. `run` and each `build` command are arrays of arguments. The evaluated container image is pinned to a digest. Do not put credentials in the manifest or project files.

## 3. One decision per request

The project is a persistent process. Standard input and standard output carry one JSON object per line. Send diagnostic logs to standard error; flush each response immediately.

- `initialize`: public configuration and catalogue. Do not reply to this message.
- `decision_request`: current snapshot and `decision_sequence`. Read current weather, available tiles, requests, progress and forecasts released so far.
- `decision_response`: return the same sequence and `protocol_version: participant-agent-protocol-v2`, with a decision to `observe` or `wait`. See the interactive examples below for the full envelope. Reports may accompany the decision.

The server commits the current decision before releasing the next observation. Future sequences are rejected. Retrying the identical current decision is safe; a conflicting replacement is rejected. The server holds future weather and anomaly answers.

A 900-second calendar slot is not necessarily one decision: an exposure can span slots and several short exposures can begin in the same slot. Follow the returned sequence and cursor.

## 4. Confirm and evaluate

The platform records the source revision and launch configuration, tests the interface and shows them for your confirmation. Start an evaluation from the confirmed version. One batch runs all three formal scenarios; each run returns decisions to the server round by round. CSV upload is not accepted.

Uploading and confirming do not use evaluations (up to 10 uploads per team per day). A version that was never evaluated can be withdrawn: it is hidden and can no longer be confirmed or evaluated. A version still being prepared can be withdrawn once preparation finishes.

Each click on "Evaluate this version" uses one of the day's evaluations. One evaluation runs every scenario of the phase once; its score is the average of those scenarios, and the online board keeps the team's best complete evaluation. Within the daily limit you may evaluate as often as you like; choose your final version (section 6) before the competition ends. Evaluations that fail because of the platform (evaluation engine, scheduling, network, timeouts and similar) are not counted and are marked "Not counted toward the daily limit"; failures caused by your program (build failure, crash, output that violates the protocol) are counted. Evaluating an already evaluated version again asks for confirmation. The daily count resets at 00:00 UTC and the page shows how many evaluations are left today.

## 5. Optional personal model APIs

Bring your own API and quota if your algorithm needs a model. The platform does not provide model credits. Do not commit keys to your repository or ZIP.

Enter a supported HTTPS endpoint, model and key in Participate and choose how the key is handled. Either way, the key never enters project files, run artifacts or logs.

- **Do not save (default)**: the key stays only in your open page and is never stored on the server. Keep the page open until each evaluation finishes; model calls fail while it is closed. **The hidden final evaluation cannot use such a key: teams whose program calls a large model must switch to “Save encrypted” before the competition ends, otherwise model calls fail in the hidden final evaluation.** If your team is verified, open the page at the time agreed with the organizers.
- **Save encrypted (opt-in)**: the key is stored encrypted on the server, used only for evaluation and verification, and deleted automatically once the competition has ended and the results have been verified. The page does not need to stay open during evaluation; you can replace or delete a saved key at any time.

Switching from "save encrypted" to "do not save" deletes the stored key immediately.

Deterministic algorithms do not need a key. Explanation length does not increase the performance score.

## 6. Fixed scenarios, final version and the hidden final

The online competition evaluates on three **fixed** formal scenarios (A, B and C). They are the same for every team and every evaluation: there is no per-team randomization. Their files, weather, forecasts and events are not published; your project receives observations one step at a time during an evaluation. The score is the total defined in [Rules](/rules); the batch score is the mean over the three scenarios. The result ZIP of each of your own evaluations can be downloaded as before.

A batch includes all three scenarios and ranks only when they all finish. The **online board** keeps each team's best complete batch, without mixing the best scenario scores from different attempts. It updates live and is for feedback: it does **not** decide the final ranking.

**Final version.** In Participate, under "Final version", any team member can mark one confirmed version as the team's final version and change or clear the choice until the online competition ends (Oct 7 23:59 UTC+8). After that it is locked. Without a choice, the version of your best evaluation on the online board is used. A chosen version cannot be withdrawn.

**Hidden final.** After the online competition ends, the organizers evaluate each team's final version exactly once on one hidden scenario that nobody has seen. It does not use your daily evaluations. Its data, run logs and results stay private until the organizers publish the final results, and **only this hidden score decides the final ranking**. No team page is open during it: **if your program calls a large model, switch the model API to “Save encrypted” before the competition ends; otherwise model calls will fail in the hidden final evaluation.** Teams that do not use a model are unaffected.

## 7. Results and reproduction

The result records decisions, scores, runtime status and logs; download it from Participate. Results of the hidden final evaluation become available only after the final results are published. The platform's private audit record retains the source revision and file digests so organizers can re-score the decisions. Future data and private credentials are never included in participant downloads.

Keep your own source version, launch settings and reproduction notes. Design review considers code, run records and reproduction separately from the performance board.
