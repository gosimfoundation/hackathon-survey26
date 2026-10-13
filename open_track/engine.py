"""Trusted engine for the open track (holds the hidden bundle, never runs participant code).

For each claimed run: derive the hidden seed, run the task environment, exchange public protocol
messages with the executor through the database, then score by deterministic replay of the decision
log (aohkit.runner.replay), charging the model usage the executor's proxy metered.

    python -m open_track.engine --max-seconds 19800
Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, OPEN_TRACK_BUNDLE_KEY (engine-only secret), OPEN_WORKER_ID,
and either OPEN_TRACK_BUNDLE (local path of the sealed bundle) or OPEN_TRACK_BUNDLE_OBJECT
(default open-private/hidden-v1.bundle in the private storage bucket).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from worker.supa import Supa, SupabaseError

from open_track import crypto

PROTO = "aoh-protocol-v1"
PROBLEMS = Path(__file__).resolve().parent / "problems"
POLL = float(os.environ.get("OPEN_POLL_SECONDS", "0.05"))
EXEC_WAIT = float(os.environ.get("OPEN_EXEC_WAIT_SECONDS", "900"))   # executor must start the agent by then
USAGE_WAIT = float(os.environ.get("OPEN_USAGE_WAIT_SECONDS", "120"))
# Database round trips are not the agent's fault: each decision gets this much extra wall clock, capped.
LATENCY_ALLOWANCE = float(os.environ.get("OPEN_LATENCY_ALLOWANCE_SECONDS", "0.5"))
LATENCY_CAP = float(os.environ.get("OPEN_LATENCY_CAP_SECONDS", "120"))
PUBLIC_KEYS = ("total", "max_possible", "llm_cost", "status", "decisions", "elapsed_seconds", "replay_consistent")


class ExecutorMissing(RuntimeError):
    pass


def prepare_root(bundle: bytes, bundle_key: str) -> Path:
    """Private copy of the public task packages plus the hidden bundle; aohkit is imported from here."""
    root = Path(tempfile.mkdtemp(prefix="aoh-engine-"))
    shutil.copytree(PROBLEMS, root, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "docs"))
    crypto.extract_hidden(bundle, bundle_key, str(root))
    os.environ["AOH_HIDDEN_SALT"] = str(root / "_hidden" / "salt.txt")
    sys.path.insert(0, str(root))
    return root


def public_summary(report: dict) -> dict:
    """Numbers only: per-event details of a fixed hidden seed would leak the test."""
    out = {k: report[k] for k in PUBLIC_KEYS if k in report}
    for k, v in report.items():
        if k not in out and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = v
    out["llm"] = report.get("llm", {})
    return out


class DbAgent:
    """The agent as seen from the engine: protocol lines through private.open_messages."""

    def __init__(self, supa: Supa, run_id: str, worker: str, attempt: int):
        self.supa, self.run, self.worker, self.attempt = supa, run_id, worker, attempt
        self.out_seq = 0
        self.in_after = 0

    def send(self, msg: dict) -> None:
        self.out_seq += 1
        for attempt in range(4):
            try:
                self.supa.rpc("open_engine_post", {"p_run": self.run, "p_worker": self.worker, "p_attempt": self.attempt,
                                                   "p_seq": self.out_seq, "p_body": msg})
                return
            except SupabaseError as exc:
                if attempt == 3 or "run_not_owned" in exc.body:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def poll(self, direction: str = "from_agent") -> list[dict]:
        rows = self.supa.rpc("open_engine_fetch", {"p_run": self.run, "p_attempt": self.attempt, "p_direction": direction,
                                                   "p_after": self.in_after if direction == "from_agent" else 0}) or []
        if direction == "from_agent" and rows:
            self.in_after = rows[-1]["seq"]
        return [r["body"] for r in rows]

    def wait_ready(self, timeout: float) -> None:
        end = time.time() + timeout
        while time.time() < end:
            for body in self.poll():
                if body.get("message_type") == "executor_ready":
                    return
                if body.get("message_type") == "executor_failed":
                    raise RuntimeError("executor could not start the agent: " + str(body.get("reason", ""))[:300])
            time.sleep(max(POLL, 0.5))
        raise ExecutorMissing("no executor started the agent in time")

    def usage(self, timeout: float) -> dict | None:
        end = time.time() + timeout
        while time.time() < end:
            rows = self.poll("usage")
            if rows:
                return rows[-1]
            time.sleep(0.5)
        return None


def evaluate(supa: Supa, job: dict, worker: str) -> None:
    from aohkit import runner as aoh  # imported from the prepared root
    run_id, problem, index = job["run_id"], job["problem_id"], int(job["seed_index"])
    mod = aoh.load_problem(problem)
    seed = aoh.hidden_seed(problem, index)
    env = mod.make_env(seed)
    init = env.initialize()
    # the task's own wall clock (same as the local runner); open_problems.wallclock_seconds is only the fallback
    budget = float(init.get("global_wallclock_seconds") or job.get("wallclock_seconds") or 600)
    attempt = int(job["attempt"])
    agent = DbAgent(supa, run_id, worker, attempt)
    try:
        agent.wait_ready(EXEC_WAIT)
    except ExecutorMissing:
        supa.rpc("open_release", {"p_run": run_id, "p_worker": worker, "p_attempt": attempt})
        print(f"{run_id}: released (no executor)", flush=True)
        return
    actions, status = [], "ok"
    t0 = time.time()
    try:
        agent.send({"protocol_version": PROTO, "message_type": "initialize", "payload": init})
        seq = 0
        while not env.done:
            snap = env.snapshot()
            seq += 1
            agent.send({"protocol_version": PROTO, "message_type": "decision_request", "decision_sequence": seq, "payload": snap})
            action = None
            while action is None:
                if time.time() - t0 > budget + min(LATENCY_ALLOWANCE * seq, LATENCY_CAP):
                    raise TimeoutError
                for msg in agent.poll():
                    mt = msg.get("message_type")
                    if mt == "agent_exited":
                        raise BrokenPipeError
                    if mt == "decision_response" and msg.get("decision_sequence") == seq:
                        action = msg.get("action") if isinstance(msg.get("action"), dict) else {"type": "wait"}
                if action is None:
                    time.sleep(POLL)
            actions.append(action)
            env.step(action)
    except TimeoutError:
        status = "wallclock_exhausted"
    except BrokenPipeError:
        status = "agent_error"
    agent.send({"protocol_version": PROTO, "message_type": "finished", "payload": {}})
    elapsed = time.time() - t0
    got = agent.usage(USAGE_WAIT)
    usage = {"calls": 0, "tokens_in": 0, "tokens_out": 0}
    if got:
        usage = {k: int(got.get(k, 0)) for k in usage}
    report = aoh.replay(mod, seed, actions, usage)
    if status == "ok":
        report["replay_consistent"] = abs(env.score_report(usage)["total"] - report["total"]) < 1e-6
    report.update({"problem": problem, "status": status, "decisions": len(actions), "elapsed_seconds": round(elapsed, 1),
                   "llm": usage, "usage_reported": bool(got)})
    details = {"report": report, "decisions": actions, "agent_log": (got or {}).get("agent_log", "")}
    supa.rpc("open_finish", {"p_run": run_id, "p_worker": worker, "p_attempt": attempt, "p_status": "done", "p_total": report["total"],
                             "p_report": public_summary(report), "p_error": "" if got else "model usage not reported",
                             "p_details": details})
    print(f"{run_id}: {problem}#{index} {status} total={report['total']}", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=float, default=19800)
    ap.add_argument("--once", action="store_true", help="exit when the queue is empty")
    a = ap.parse_args(argv)
    supa = Supa(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    if os.environ.get("OPEN_TRACK_BUNDLE"):
        bundle = Path(os.environ["OPEN_TRACK_BUNDLE"]).read_bytes()
    else:
        bucket, _, path = os.environ.get("OPEN_TRACK_BUNDLE_OBJECT", "open-private/hidden-v1.bundle").partition("/")
        bundle = supa.download(bucket, path)
    prepare_root(bundle, os.environ["OPEN_TRACK_BUNDLE_KEY"])
    worker = os.environ.get("OPEN_WORKER_ID", f"engine-{os.getpid()}")
    end = time.time() + a.max_seconds
    while time.time() < end:
        supa.rpc("open_requeue_stale", {"p_minutes": 45})
        job = supa.rpc("open_engine_claim", {"p_worker": worker})
        if not job:
            if a.once:
                return
            time.sleep(10)
            continue
        try:
            evaluate(supa, job, worker)
        except Exception as exc:  # noqa: BLE001 - one broken run must not stop the queue
            print(f"{job['run_id']}: engine error {type(exc).__name__}: {exc}", flush=True)
            try:
                supa.rpc("open_finish", {"p_run": job["run_id"], "p_worker": worker, "p_attempt": job["attempt"], "p_status": "failed",
                                         "p_total": None, "p_report": {}, "p_error": f"engine error: {type(exc).__name__}"})
            except SupabaseError:
                pass


if __name__ == "__main__":
    main()
