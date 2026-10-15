"""Open track end to end: browser-style submission -> engine (hidden bundle) + executor (Docker) on
separate processes -> official scores -> public board.

Needs Docker and the organizer's hidden material, so it is skipped unless
  OPEN_TRACK_E2E_HIDDEN_ROOT  directory with _hidden/salt.txt and _hidden/nl/*.json
  OPEN_TRACK_E2E_AGENT        an agent.py known to score deterministically without a model
  OPEN_TRACK_E2E_EXPECTED     JSON {"problem": "...", "totals": [..per hidden index..]}
are set (and OPEN_WORK_DIR when the Docker daemon cannot see the system temp folder).
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from conftest import Client, signup
import psycopg
from harness import anon_key, jwt_encode, service_key

ROOT = Path(__file__).resolve().parents[2]
HIDDEN = os.environ.get("OPEN_TRACK_E2E_HIDDEN_ROOT")
AGENT = os.environ.get("OPEN_TRACK_E2E_AGENT")
EXPECTED = os.environ.get("OPEN_TRACK_E2E_EXPECTED")

pytestmark = pytest.mark.skipif(not (HIDDEN and AGENT and EXPECTED and shutil.which(os.environ.get("DOCKER", "docker"))),
                                reason="open-track e2e needs Docker and the hidden bundle inputs")


def executor_env(hs, base_env: dict, private_pem: str) -> dict:
    """The executor's environment: anon key + open_executor JWT, never the service key."""
    with psycopg.connect(hs.db_uri, autocommit=True) as conn:
        conn.execute("grant open_executor to authenticator")
    env = {k: v for k, v in base_env.items() if k != "SUPABASE_SERVICE_ROLE_KEY"}
    env.update(SUPABASE_ANON_KEY=anon_key(), OPEN_EXECUTOR_TOKEN=jwt_encode({"role": "open_executor", "exp": 4102444800}),
               OPEN_TRACK_KEY_PRIVATE=private_pem, OPEN_WORKER_ID="e2e-exec")
    if os.environ.get("OPEN_WORK_DIR"):
        env["OPEN_WORK_DIR"] = os.environ["OPEN_WORK_DIR"]
    return env


def test_submission_is_scored_like_the_local_runner(hs, service, tmp_path):
    expected = json.loads(EXPECTED)
    problem, totals = expected["problem"], expected["totals"]
    sys.path.insert(0, str(ROOT))
    from open_track import crypto

    # organizer material: sealed hidden bundle (engine only) and executor key pair
    key = base64.b64encode(os.urandom(32)).decode()
    bundle = tmp_path / "hidden.bundle"
    bundle.write_bytes(crypto.seal(crypto.pack_hidden(HIDDEN), key))
    crypto.keygen(str(tmp_path / "keys"))

    # participant: a ZIP with agent.py only, no model
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(AGENT, "agent.py")
    c = signup(hs, "open-e2e@test.org")
    st, sid = c.rpc("open_submit", {"p_problems": [problem], "p_zip_base64": base64.b64encode(buf.getvalue()).decode()})
    assert st == 200, sid

    base_env = {k: v for k, v in os.environ.items() if not k.startswith("OPEN_TRACK_")}
    base_env.update(SUPABASE_URL=hs.url, SUPABASE_SERVICE_ROLE_KEY=service_key(), PYTHONPATH=str(ROOT),
                    NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    # the two sides get disjoint secrets, as in .github/workflows/open-worker.yml
    engine_env = {**base_env, "OPEN_TRACK_BUNDLE": str(bundle), "OPEN_TRACK_BUNDLE_KEY": key, "OPEN_WORKER_ID": "e2e-engine"}
    exec_env = executor_env(hs, base_env, (tmp_path / "keys" / "private.pem").read_text())
    logs = tmp_path
    ex = subprocess.Popen([sys.executable, "-m", "open_track.executor", "--once", "--idle-seconds", "60"], cwd=ROOT,
                          env=exec_env, stdout=open(logs / "executor.log", "w"), stderr=subprocess.STDOUT)
    en = subprocess.run([sys.executable, "-m", "open_track.engine", "--once"], cwd=ROOT, env=engine_env,
                        capture_output=True, text=True, timeout=3600)
    ex.wait(timeout=600)
    print(en.stdout[-3000:], en.stderr[-3000:], (logs / "executor.log").read_text()[-3000:])
    assert en.returncode == 0

    st, runs = c.select("open_runs", f"select=seed_index,status,total,report,error&submission_id=eq.{sid}&order=seed_index")
    assert st == 200 and len(runs) == len(totals)
    for r, want in zip(runs, totals):
        assert r["status"] == "done", r
        assert r["report"]["status"] == "ok" and r["report"]["replay_consistent"] is True
        assert round(r["total"], 1) == round(want, 1), (r["seed_index"], r["total"], want)
        assert r["report"]["llm"] == {"calls": 0, "tokens_in": 0, "tokens_out": 0}
        assert "reports" not in r["report"]  # per-event details stay organizer-only
    st, subs = c.select("open_submissions", f"select=status&id=eq.{sid}")
    assert subs == [{"status": "done"}]
    st, board = Client(hs.url).rpc("open_leaderboard")
    row = next(r for r in board if r["problem_id"] == problem)
    assert round(row["best_total"], 2) == round(sum(totals) / len(totals), 2)


MODEL = {k: os.environ.get(f"OPEN_TRACK_E2E_MODEL_{k.upper()}") for k in ("base", "name", "key")}
LLM_AGENT = '''
from aohkit.agent_base import serve
from aohkit.llm import ask
state = {"asked": False}
def decide(init, snap):
    if not state["asked"]:
        state["asked"] = True
        try:
            ask("Reply with the single word OK.", max_tokens=200)
        except Exception as e:
            import sys; print("ask failed", e, file=sys.stderr)
    return {"type": "wait"}
serve(decide)
'''


@pytest.mark.skipif(not all(MODEL.values()), reason="needs OPEN_TRACK_E2E_MODEL_BASE/NAME/KEY (a participant's own API)")
def test_model_submission_key_stays_encrypted_and_usage_is_charged(hs, service, tmp_path):
    import psycopg
    sys.path.insert(0, str(ROOT))
    from open_track import crypto
    key = base64.b64encode(os.urandom(32)).decode()
    bundle = tmp_path / "hidden.bundle"
    bundle.write_bytes(crypto.seal(crypto.pack_hidden(HIDDEN), key))
    crypto.keygen(str(tmp_path / "keys"))
    ciphertext = crypto.encrypt_model_key(MODEL["key"], (tmp_path / "keys" / "public.pem").read_text())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("agent.py", LLM_AGENT)
    c = signup(hs, "open-e2e-model@test.org")
    st, sid = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": base64.b64encode(buf.getvalue()).decode(),
                                    "p_model_base": MODEL["base"], "p_model_name": MODEL["name"],
                                    "p_key_ciphertext": ciphertext, "p_key_hint": MODEL["key"][-4:]})
    assert st == 200, sid
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("OPEN_TRACK_")}
    base_env.update(SUPABASE_URL=hs.url, SUPABASE_SERVICE_ROLE_KEY=service_key(), PYTHONPATH=str(ROOT),
                    NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    exec_env = executor_env(hs, base_env, (tmp_path / "keys" / "private.pem").read_text())
    ex = subprocess.Popen([sys.executable, "-m", "open_track.executor", "--once", "--idle-seconds", "60"], cwd=ROOT,
                          env=exec_env, stdout=open(tmp_path / "executor.log", "w"), stderr=subprocess.STDOUT)
    en = subprocess.run([sys.executable, "-m", "open_track.engine", "--once"], cwd=ROOT, capture_output=True, text=True, timeout=3600,
                        env={**base_env, "OPEN_TRACK_BUNDLE": str(bundle), "OPEN_TRACK_BUNDLE_KEY": key})
    ex.wait(timeout=600)
    print(en.stdout[-2000:], en.stderr[-2000:], (tmp_path / "executor.log").read_text()[-2000:])
    st, runs = c.select("open_runs", f"select=status,total,report&submission_id=eq.{sid}")
    assert runs and all(r["status"] == "done" for r in runs), runs
    for r in runs:
        assert r["report"]["llm"]["calls"] == 1 and r["report"]["llm"]["tokens_in"] > 0, r["report"]
        assert "llm_cost" in r["report"], r["report"]  # the task charges the metered tokens (rounded to 0.1 points)
    with psycopg.connect(hs.db_uri) as conn:
        for table in ("public.open_submissions", "public.open_runs", "private.open_submission_files",
                      "private.open_messages", "private.open_run_details"):
            n = conn.execute(f"select count(*) from {table} t where t::text like %s", ("%" + MODEL["key"] + "%",)).fetchone()[0]
            assert n == 0, f"plaintext key found in {table}"
