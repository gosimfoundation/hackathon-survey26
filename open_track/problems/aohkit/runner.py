"""AOH local runner: JSON-Lines protocol, wall clock, decision log, replay scoring.

Envelope (same shape as participant-agent-protocol-v2, new version tag):
  platform -> agent  {"protocol_version":"aoh-protocol-v1","message_type":"initialize","payload":{...}}
  platform -> agent  {"protocol_version":"aoh-protocol-v1","message_type":"decision_request","decision_sequence":n,"payload":{...}}
  agent -> platform  {"protocol_version":"aoh-protocol-v1","message_type":"decision_response","decision_sequence":n,"action":{...}}
  platform -> agent  {"protocol_version":"aoh-protocol-v1","message_type":"finished","payload":{}}
Only stdout carries protocol lines; diagnostics go to stderr.

Usage:
  python3 -m aohkit.runner --problem nu_followup --seed 3 --agent "python3 my_agent.py" [--out DIR]
  python3 -m aohkit.runner --problem nu_followup --hidden 0 ...   (organizer only: needs the hidden salt)
  --sandbox DIR   confine the agent with sandbox-exec to DIR (reads/writes), network only to the LLM proxy
"""
from __future__ import annotations

import argparse, hashlib, hmac, importlib, json, os, select, shlex, subprocess, sys, tempfile, time

PROTO = "aoh-protocol-v1"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SALT_FILE = os.environ.get("AOH_HIDDEN_SALT", os.path.join(ROOT, "_hidden", "salt.txt"))


def hidden_seed(problem: str, index: int) -> int:
    salt = open(SALT_FILE, "rb").read().strip()
    return int.from_bytes(hmac.new(salt, f"{problem}:{index}".encode(), hashlib.sha256).digest()[:6], "big")


def load_problem(problem: str):
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    return importlib.import_module(f"{problem}.env")


def llm_usage(ledger: str) -> dict:
    calls = tin = tout = 0
    if os.path.exists(ledger):
        for line in open(ledger):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            calls += 1; tin += int(r.get("in", 0)); tout += int(r.get("out", 0))
    return {"calls": calls, "tokens_in": tin, "tokens_out": tout}


def replay(mod, seed: int, actions: list, usage: dict) -> dict:
    env = mod.make_env(seed)
    env.initialize()
    for a in actions:
        if env.done:
            break
        env.snapshot()
        env.step(a)
    idle = getattr(mod, "IDLE_ACTION", {"type": "wait"})
    while not env.done:  # agent stopped early (crash / wall clock): remaining decisions are the problem's idle action
        env.snapshot(); env.step(dict(idle))
    return env.score_report(usage)


def run(problem: str, seed: int, agent_cmd: str, out: str | None = None, wallclock: float | None = None,
        quiet: bool = False, sandbox_dir: str | None = None) -> dict:
    mod = load_problem(problem)
    out = out or tempfile.mkdtemp(prefix=f"aoh-{problem}-")
    os.makedirs(out, exist_ok=True)
    ledger = os.path.join(out, "llm_ledger.jsonl")
    open(ledger, "a").close()
    env = mod.make_env(seed)
    init = env.initialize()
    budget = float(wallclock or init.get("global_wallclock_seconds", 600))
    from aohkit import llm_proxy, sandbox
    srv, proxy_url = llm_proxy.start(ledger)  # organizer-side metering; agents never hold a key
    agent_env = {k: v for k, v in os.environ.items() if not k.startswith(("AOH_", "ANTHROPIC", "OPENAI", "TOKENFLUX"))}
    agent_env.update(AOH_LLM_PROXY=proxy_url, PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    if sandbox_dir:
        os.makedirs(os.path.join(sandbox_dir, "_scratch"), exist_ok=True)
        agent_env["TMPDIR"] = os.path.join(sandbox_dir, "_scratch")
        agent_env["PYTHONPATH"] = sandbox_dir
        agent_env["PYTHONDONTWRITEBYTECODE"] = "1"
        agent_cmd = ["/usr/bin/sandbox-exec", "-p", sandbox.agent_profile(sandbox_dir), "/bin/bash", "-c", f"cd {shlex.quote(sandbox_dir)} && {agent_cmd}"]
    else:
        agent_env["PYTHONPATH"] = ROOT
    proc = subprocess.Popen(agent_cmd, shell=isinstance(agent_cmd, str), cwd=sandbox_dir or None, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=open(os.path.join(out, "agent_stderr.log"), "w"), text=True, bufsize=1,
                            env=agent_env)
    t0 = time.time()
    actions, status = [], "ok"

    def send(msg):
        proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n"); proc.stdin.flush()

    try:
        send({"protocol_version": PROTO, "message_type": "initialize", "payload": init})
        seq = 0
        while not env.done:
            snap = env.snapshot()
            seq += 1
            send({"protocol_version": PROTO, "message_type": "decision_request", "decision_sequence": seq, "payload": snap})
            action = None
            while action is None:
                left = budget - (time.time() - t0)
                if left <= 0:
                    raise TimeoutError
                ready, _, _ = select.select([proc.stdout], [], [], min(left, 5))
                if not ready:
                    if proc.poll() is not None:
                        raise BrokenPipeError
                    continue
                line = proc.stdout.readline()
                if not line:
                    raise BrokenPipeError
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue  # non-protocol stdout noise is ignored
                if msg.get("message_type") == "decision_response" and msg.get("decision_sequence") == seq:
                    action = msg.get("action") if isinstance(msg.get("action"), dict) else {"type": "wait"}
            actions.append(action)
            env.step(action)
        send({"protocol_version": PROTO, "message_type": "finished", "payload": {}})
    except TimeoutError:
        status = "wallclock_exhausted"
    except (BrokenPipeError, OSError):
        status = "agent_error"
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
    elapsed = time.time() - t0
    with open(os.path.join(out, "decisions.jsonl"), "w") as f:
        for i, a in enumerate(actions, 1):
            f.write(json.dumps({"decision_sequence": i, "action": a}) + "\n")
    usage = llm_usage(ledger)
    report = replay(mod, seed, actions, usage)  # official score = deterministic replay of the log
    if status == "ok":
        live = env.score_report(usage)
        report["replay_consistent"] = abs(live["total"] - report["total"]) < 1e-6
    report.update({"problem": problem, "status": status, "decisions": len(actions), "elapsed_seconds": round(elapsed, 1),
                   "llm": usage})
    json.dump(report, open(os.path.join(out, "score_report.json"), "w"), indent=1, ensure_ascii=False)
    if not quiet:
        print(json.dumps({k: report[k] for k in ("problem", "status", "total") if k in report}, ensure_ascii=False))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--problem", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", type=int)
    g.add_argument("--hidden", type=int)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--out")
    ap.add_argument("--wallclock", type=float)
    ap.add_argument("--sandbox", help="run the agent under sandbox-exec, confined to this directory")
    a = ap.parse_args(argv)
    seed = a.seed if a.seed is not None else hidden_seed(a.problem, a.hidden)
    r = run(a.problem, seed, a.agent, a.out, a.wallclock, sandbox_dir=os.path.realpath(a.sandbox) if a.sandbox else None)
    print(json.dumps(r, ensure_ascii=False, indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
