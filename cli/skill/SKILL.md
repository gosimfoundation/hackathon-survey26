---
name: survey26
description: Use the official survey26 command-line tool of the GOSIM 2026 Agentic Observer Hackathon (create.gosim.org/survey26) to upload or confirm a project, start and wait for evaluations, read logs and results, check quotas and leaderboards, and choose the final version. Use when the user mentions survey26, the Agentic Observer hackathon, evaluating or submitting an observer agent, or SURVEY26_TOKEN.
---

# survey26: hackathon command-line tool

`survey26` does from a terminal everything the hackathon website lets a contestant do, with the same permissions,
daily limits and quotas. Full guide: https://create.gosim.org/survey26/platform/cli
(agent version: https://create.gosim.org/survey26/platform/survey26-AGENTS.md).

## Rules you must follow

- **Never print, log, commit or zip the token.** Read it only from the environment variable `SURVEY26_TOKEN`
  (or the saved `survey26 login`). Do not echo it, do not pass it as a command argument, do not put it in project files.
- **No human-in-the-loop decisions during an evaluation.** Every decision of the evaluated program must be made by the
  program itself. Do not build anything that lets a person steer a running evaluation.
- **Evaluations are a shared, limited team budget.** `eval start` uses 1 of the team's evaluations for the day,
  `eval selfcheck` uses 3. Before starting one, check `survey26 quota` and evaluate only a version that passed its
  public test. Never start evaluations in an unattended loop. If the user has not asked you to evaluate, ask first.
- Organizer functions, token creation and account login are not available with a token; do not try to work around that.

## 1. Set up

```bash
command -v survey26 || curl -fsSLO https://create.gosim.org/survey26/platform/survey26.py
survey26 --version            # or: python3 survey26.py --version   (1.9.1 or later)
test -n "$SURVEY26_TOKEN" && survey26 --json whoami
```

If `survey26` is not on the `PATH`, run `python3 survey26.py` wherever this file writes `survey26`
(Python 3.9+, no other packages). Prebuilt binaries (no Python) are linked from the guide.
If `SURVEY26_TOKEN` is not set, ask the user to create a personal API token on the website
(Profile → Personal API tokens, starts with `s26_`) and to export it themselves:
`export SURVEY26_TOKEN=s26_...`. Do not ask them to paste it into the chat.

Always add `--json`: the output is one object `{"ok": ..., "data": ...}` or `{"ok": false, "error": {"code", "message", "exit_code"}}`.
Act on `ok`, `error.code` and the exit code.

## 2. Model keys and network (only if the program calls a model)

```bash
survey26 --json env show
survey26 --json env model --provider kimi --key - < key.txt        # key from stdin, never as an argument
survey26 --json env set NAME --from-env VAR                          # any other secret
```

The cards of one evaluation run at the same time in separate containers. To spread model requests, save several keys
(`KIMI_KEY_1` … `KIMI_KEY_8`) and let each container pick one (by `task_card.card_id` from the `initialize` message,
or at random). The program must wait and retry on HTTP 429 instead of failing.

## 3. Upload and confirm a project

```bash
survey26 --json project upload agent.zip --title "short description"     # 1 of 10 daily uploads
# or: survey26 --json project submit-repo https://github.com/OWNER/REPO [--branch B] [--subdir DIR]
survey26 --json project wait REV          # preparation and public test; exit 9 = failed
survey26 project logs REV                 # build log and the public test's agent.log
survey26 --json project show REV --files  # review execution settings and adapter files
survey26 --json project confirm REV --yes # confirming states the team reviewed them
```

`REV`, `BATCH` and `RUN` accept a unique prefix of at least 4 characters. If preparation fails, read
`project logs`, fix the project and upload again.

## 4. Evaluate and wait

```bash
survey26 --json quota                          # evaluations left today, reset time
survey26 --json eval start REV --yes           # --yes is needed with --json when re-evaluating a version
survey26 --json eval wait --first-stage        # returns when cards A–D are done (about 25 min)
survey26 --json eval wait --timeout 7200       # all 8 cards (about 1 to 1.5 hours)
survey26 --json eval show latest               # live status of each card
```

In the online competition each evaluation runs cards A–D first, then A1–D1 automatically. `eval show` reports for
every card `status`, `running_minutes` and `waiting_for_first_stage`; the evaluation's `first_stage_score` is the
mean of A–D (its online board score). Do not poll in a tight loop: use `eval wait`.
A queued evaluation that has not started can be cancelled (not counted): `survey26 --json eval cancel BATCH --yes`. The same command stops a running evaluation: its unfinished cards are not scored and it still counts toward today's evaluations, so stop only when the user asks.

## 5. Results and logs

```bash
survey26 --json results show latest
survey26 results log RUN --tail 200            # platform diagnostics + agent.log of one card
survey26 --json results download-all latest -o results.zip
survey26 --json leaderboard --mine             # online board; --card v4-a, --card super for the super board
survey26 --json final show                     # final version (defaults to the best evaluation)
survey26 --json final set REV                  # only if the user asks
```

## 6. Errors and limits

| Exit | Meaning | What to do |
| --- | --- | --- |
| 1 | refused (`error.code`) | read `error.message`; fix the cause |
| 2 | usage, ambiguous ID, or `--yes` needed | fix the command; add `--yes` only for an action the user wants |
| 3 | token missing, invalid or revoked | ask the user to set a valid `SURVEY26_TOKEN` |
| 4 | not found | check the ID with `project list` / `eval list` |
| 5 | too many requests (120/min) | wait one minute, then retry |
| 6 | network or server unavailable | retry later |
| 7 | `wait` timed out | run the wait command again |
| 8 | daily or team limit (`daily_limit`, `batch_already_active`, …) | stop; report to the user; quotas reset at 00:00 UTC |
| 9 | preparation or evaluation failed | read `project logs` or `results log RUN` |

Report to the user what you did: version IDs, evaluation IDs, scores per card, and the evaluations left today.
