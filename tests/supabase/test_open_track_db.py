"""Open track for the new AOH tasks: submission rules, privacy, worker hand-off and the public board.

Migration 20261013000000_open_track.sql; workers in open_track/.
"""
from __future__ import annotations

import base64
import io
import uuid
import zipfile

import psycopg
import pytest

from conftest import Client, signup
from harness import jwt_encode

TASKS = ["nu_followup_v5", "cr_array_v5", "sn_burst_v4", "osc_run_v3"]


def agent_zip(text: str = "print('hi')\n") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("agent.py", text)
    return base64.b64encode(buf.getvalue()).decode()


def user(hs, nickname: str = "") -> tuple[Client, str]:
    c = signup(hs, f"open-{uuid.uuid4().hex}@test.org")
    st, me = c.rpc("me")
    assert st == 200
    uid = me["id"] if isinstance(me, dict) else me[0]["id"]
    if nickname:
        st, _ = c.call("PATCH", f"/rest/v1/profiles?id=eq.{uid}", {"nickname": nickname})
        assert st in (200, 204)
    return c, uid


@pytest.fixture(scope="module")
def executor(hs):
    """The executor job's identity: role open_executor, never the service key."""
    with psycopg.connect(hs.db_uri, autocommit=True) as conn:
        conn.execute("grant open_executor to authenticator")
    return Client(hs.url, jwt_encode({"role": "open_executor", "exp": 4102444800}))


def test_tasks_are_listed_publicly(hs):
    st, rows = Client(hs.url).select("open_problems", "select=id,version,seed_indices,active&order=sort")
    assert st == 200
    assert [r["id"] for r in rows] == TASKS
    assert all(r["active"] and len(r["seed_indices"]) == 5 for r in rows)


def test_individual_can_submit_any_subset_once_each(hs):
    c, uid = user(hs)
    st, sid = c.rpc("open_submit", {"p_problems": ["sn_burst_v4"], "p_zip_base64": agent_zip()})
    assert st == 200, sid
    st, runs = c.select("open_runs", f"select=problem_id,seed_index,status&submission_id=eq.{sid}")
    assert st == 200
    assert sorted((r["problem_id"], r["seed_index"]) for r in runs) == [("sn_burst_v4", i) for i in range(5)]
    assert {r["status"] for r in runs} == {"queued"}
    st, sid2 = c.rpc("open_submit", {"p_problems": ["osc_run_v3", "cr_array_v5"], "p_zip_base64": agent_zip()})
    assert st == 200, sid2


def test_submission_validation(hs):
    c, _ = user(hs)
    for args, err in [
        ({"p_problems": [], "p_zip_base64": agent_zip()}, "invalid_problems"),
        ({"p_problems": ["no_such_task"], "p_zip_base64": agent_zip()}, "invalid_problems"),
        ({"p_problems": ["sn_burst_v4", "sn_burst_v4"], "p_zip_base64": agent_zip()}, "invalid_problems"),
        ({"p_problems": ["sn_burst_v4"], "p_zip_base64": base64.b64encode(b"not a zip at all, sorry").decode()}, "invalid_zip"),
        ({"p_problems": ["sn_burst_v4"], "p_zip_base64": "!!!"}, "invalid_zip"),
        ({"p_problems": ["sn_burst_v4"], "p_zip_base64": agent_zip(), "p_key_ciphertext": "QUJD",
          "p_model_base": "http://insecure.example/v1", "p_model_name": "m"}, "invalid_model"),
        ({"p_problems": ["sn_burst_v4"], "p_zip_base64": agent_zip(), "p_key_ciphertext": "QUJD",
          "p_model_base": "https://my-own-server.example.com/v1", "p_model_name": "m"}, "model_host_not_allowed"),
    ]:
        st, out = c.rpc("open_submit", args)
        assert st >= 400 and err in str(out), (args, out)
    st, out = Client(hs.url).rpc("open_submit", {"p_problems": ["sn_burst_v4"], "p_zip_base64": agent_zip()})
    assert st >= 400


def test_pending_and_daily_limits(hs, service):
    c, uid = user(hs)
    for _ in range(2):
        st, _ = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
        assert st == 200
    st, out = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
    assert st >= 400 and "too_many_pending" in str(out)
    # cancelling frees a slot; the daily cap (10) still applies
    st, subs = c.select("open_submissions", "select=id&order=created_at")
    for s in subs:
        assert c.rpc("open_cancel", {"p_submission": s["id"]})[0] == 200
    n = 2
    while n < 10:
        st, sid = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
        assert st == 200, sid
        c.rpc("open_cancel", {"p_submission": sid})
        n += 1
    st, out = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
    assert st >= 400 and "daily_limit" in str(out)


def test_participants_see_only_their_own_rows_and_never_files_or_keys(hs, service):
    a, _ = user(hs)
    b, _ = user(hs)
    st, sid = a.rpc("open_submit", {"p_problems": ["cr_array_v5"], "p_zip_base64": agent_zip(),
                                    "p_model_base": "https://api.openai.com/v1", "p_model_name": "m1",
                                    "p_key_ciphertext": base64.b64encode(b"\x01" * 256).decode(), "p_key_hint": "wxyz"})
    assert st == 200, sid
    assert b.select("open_submissions", f"select=id&id=eq.{sid}") == (200, [])
    assert b.select("open_runs", f"select=id&submission_id=eq.{sid}") == (200, [])
    st, rows = a.select("open_submissions", f"select=*&id=eq.{sid}")
    assert st == 200 and rows[0]["uses_model"] and rows[0]["key_hint"] == "wxyz"
    assert "key_ciphertext" not in rows[0] and "zip" not in rows[0]
    for c in (a, Client(hs.url)):
        st, _ = c.select("open_submission_files")
        assert st >= 400
        assert c.rpc("open_exec_claim", {"p_worker": "x"})[0] >= 400
        assert c.rpc("open_engine_claim", {"p_worker": "x"})[0] >= 400
        assert c.rpc("open_exec_alive", {"p_run": str(uuid.uuid4()), "p_worker": "x", "p_attempt": 1})[0] >= 400
        assert c.rpc("open_engine_fetch", {"p_run": str(uuid.uuid4()), "p_attempt": 1, "p_direction": "from_agent", "p_after": 0})[0] >= 400
        assert c.rpc("open_exec_fetch", {"p_run": str(uuid.uuid4()), "p_worker": "x", "p_attempt": 1, "p_after": 0})[0] >= 400
    # direct writes are refused
    assert a.call("POST", "/rest/v1/open_runs", {"submission_id": sid, "problem_id": "cr_array_v5", "seed_index": 9})[0] >= 400
    assert a.call("PATCH", f"/rest/v1/open_runs?submission_id=eq.{sid}", {"status": "done", "total": 1e9})[0] in (200, 204, 401, 403, 404)
    st, runs = a.select("open_runs", f"select=status,total&submission_id=eq.{sid}")
    assert all(r["status"] == "queued" and r["total"] is None for r in runs)
    assert a.call("PATCH", f"/rest/v1/open_problems?id=eq.cr_array_v5", {"active": False})[0] in (200, 204, 401, 403, 404)
    assert Client(hs.url).select("open_problems", "select=active&id=eq.cr_array_v5")[1] == [{"active": True}]


def drain(service, executor, worker="t"):
    """Finish every queued run (engine + executor claims, a short exchange, a score)."""
    done = []
    while True:
        st, job = service.rpc("open_engine_claim", {"p_worker": worker})
        assert st == 200
        if not job:
            return done
        st, ex = executor.rpc("open_exec_claim", {"p_worker": worker + "-x"})
        assert st == 200 and ex["run_id"] == job["run_id"] and ex["attempt"] == job["attempt"]
        assert "seed_index" not in ex and "zip_base64" not in job
        rid, att = job["run_id"], job["attempt"]
        assert service.rpc("open_engine_post", {"p_run": rid, "p_worker": worker, "p_attempt": att, "p_seq": 1, "p_body": {"m": 1}})[0] in (200, 204)
        st, msgs = executor.rpc("open_exec_fetch", {"p_run": rid, "p_worker": worker + "-x", "p_attempt": att, "p_after": 0})
        assert st == 200 and msgs == [{"seq": 1, "body": {"m": 1}}]
        assert executor.rpc("open_exec_post", {"p_run": rid, "p_worker": worker + "-x", "p_attempt": att, "p_direction": "from_agent",
                                               "p_seq": 1, "p_body": {"r": 1}})[0] in (200, 204)
        assert service.rpc("open_engine_fetch", {"p_run": rid, "p_attempt": att, "p_direction": "from_agent", "p_after": 0})[1] == [{"seq": 1, "body": {"r": 1}}]
        done.append(job)
        total = 100.0 + job["seed_index"]
        assert service.rpc("open_finish", {"p_run": rid, "p_worker": worker, "p_attempt": att, "p_status": "done", "p_total": total,
                                           "p_report": {"total": total}})[0] in (200, 204)


def test_executor_role_cannot_act_as_engine_or_read_private_data(hs, service, executor):
    drain(service, executor, "pre0")
    c, _ = user(hs)
    st, sid = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
    st, job = service.rpc("open_engine_claim", {"p_worker": "e"})
    st, ex = executor.rpc("open_exec_claim", {"p_worker": "x"})
    rid, att = job["run_id"], job["attempt"]
    for name, args in [("open_engine_claim", {"p_worker": "x"}),
                       ("open_finish", {"p_run": rid, "p_worker": "e", "p_attempt": att, "p_status": "done", "p_total": 1e9, "p_report": {}}),
                       ("open_engine_post", {"p_run": rid, "p_worker": "e", "p_attempt": att, "p_seq": 9, "p_body": {}}),
                       ("open_engine_fetch", {"p_run": rid, "p_attempt": att, "p_direction": "from_agent", "p_after": 0}),
                       ("open_release", {"p_run": rid, "p_worker": "e", "p_attempt": att}),
                       ("open_requeue_stale", {"p_minutes": 0})]:
        assert executor.rpc(name, args)[0] >= 400, name
    for table in ("open_submission_files", "open_run_details", "open_messages"):
        assert executor.select(table)[0] >= 400
    # the executor may only write agent-side directions, for its own attempt
    assert executor.rpc("open_exec_post", {"p_run": rid, "p_worker": "x", "p_attempt": att, "p_direction": "to_agent",
                                           "p_seq": 1, "p_body": {}})[0] >= 400
    assert executor.rpc("open_exec_post", {"p_run": rid, "p_worker": "other", "p_attempt": att, "p_direction": "from_agent",
                                           "p_seq": 1, "p_body": {}})[0] >= 400
    assert executor.rpc("open_exec_post", {"p_run": rid, "p_worker": "x", "p_attempt": att + 1, "p_direction": "usage",
                                           "p_seq": 1, "p_body": {"calls": 0}})[0] >= 400
    # a stale engine (wrong worker or attempt) cannot finish the run
    assert service.rpc("open_finish", {"p_run": rid, "p_worker": "zombie", "p_attempt": att, "p_status": "done", "p_total": 5.0, "p_report": {}})[0] >= 400
    assert service.rpc("open_finish", {"p_run": rid, "p_worker": "e", "p_attempt": att, "p_status": "done", "p_total": 5.0, "p_report": {}})[0] in (200, 204)
    drain(service, executor, "post0")


def test_worker_handoff_board_and_old_tables_untouched(hs, service, executor):
    with psycopg.connect(hs.db_uri) as conn:
        drain(service, executor, "pre")  # clear earlier tests' queue
        before = {t: conn.execute(f"select count(*) from public.{t}").fetchone()[0]
                  for t in ("profiles", "teams", "observer_runs", "submissions")
                  if conn.execute("select to_regclass(%s)", (f"public.{t}",)).fetchone()[0]}
    a, _ = user(hs, nickname="观星者A")
    b, _ = user(hs)
    st, sa = a.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
    assert st == 200
    st, sb = b.rpc("open_submit", {"p_problems": ["osc_run_v3", "sn_burst_v4"], "p_zip_base64": agent_zip()})
    assert st == 200
    jobs = drain(service, executor)
    assert len(jobs) == 15
    st, subs = a.select("open_submissions", f"select=status&id=eq.{sa}")
    assert subs == [{"status": "done"}]
    st, scores = b.select("open_submission_scores", f"select=problem_id,mean_total,seeds_done&submission_id=eq.{sb}")
    assert st == 200 and sorted((r["problem_id"], r["mean_total"], r["seeds_done"]) for r in scores) == [
        ("osc_run_v3", 102.0, 5), ("sn_burst_v4", 102.0, 5)]
    st, board = Client(hs.url).rpc("open_leaderboard")
    assert st == 200
    osc = [r for r in board if r["problem_id"] == "osc_run_v3"]
    assert any(r["player"] == "观星者A" for r in osc)
    assert any(r["player"].startswith("player-") for r in osc)
    assert all("@" not in r["player"] for r in board)
    with psycopg.connect(hs.db_uri) as conn:
        after = {t: conn.execute(f"select count(*) from public.{t}").fetchone()[0] for t in before}
    assert after["teams"] == before["teams"]
    for t in ("observer_runs", "submissions"):
        if t in before:
            assert after[t] == before[t]


def test_stale_runs_go_back_to_the_queue_and_keep_old_messages(hs, service, executor):
    drain(service, executor, "pre2")
    c, _ = user(hs)
    st, sid = c.rpc("open_submit", {"p_problems": ["osc_run_v3"], "p_zip_base64": agent_zip()})
    assert st == 200
    st, job = service.rpc("open_engine_claim", {"p_worker": "e"})
    rid, att = job["run_id"], job["attempt"]
    executor.rpc("open_exec_claim", {"p_worker": "x"})
    executor.rpc("open_exec_post", {"p_run": rid, "p_worker": "x", "p_attempt": att, "p_direction": "from_agent", "p_seq": 1, "p_body": {"a": 1}})
    with psycopg.connect(hs.db_uri, autocommit=True) as conn:
        conn.execute("update public.open_runs set engine_claimed_at = now() - interval '2 hours' where id = %s", (rid,))
    # a live executor heartbeat keeps the run (its agent may be calling a paid API)
    assert executor.rpc("open_exec_alive", {"p_run": rid, "p_worker": "x", "p_attempt": att}) == (200, True)
    assert service.rpc("open_requeue_stale", {"p_minutes": 45}) == (200, 0)
    with psycopg.connect(hs.db_uri, autocommit=True) as conn:
        conn.execute("update public.open_runs set exec_seen_at = now() - interval '10 minutes' where id = %s", (rid,))
    st, n = service.rpc("open_requeue_stale", {"p_minutes": 45})
    assert st == 200 and n == 1
    # the old executor learns it lost the run, and can no longer write
    assert executor.rpc("open_exec_alive", {"p_run": rid, "p_worker": "x", "p_attempt": att}) == (200, False)
    st, job2 = service.rpc("open_engine_claim", {"p_worker": "e2"})
    assert job2["run_id"] == rid and job2["attempt"] == att + 1
    assert executor.rpc("open_exec_post", {"p_run": rid, "p_worker": "x", "p_attempt": att, "p_direction": "usage",
                                           "p_seq": 1, "p_body": {"calls": 0}})[0] >= 400
    # the new attempt starts with an empty exchange; the old one is kept, not deleted
    assert service.rpc("open_engine_fetch", {"p_run": rid, "p_attempt": att + 1, "p_direction": "from_agent", "p_after": 0}) == (200, [])
    with psycopg.connect(hs.db_uri) as conn:
        assert conn.execute("select count(*) from private.open_messages where run_id = %s", (rid,)).fetchone()[0] == 1
    st, ex2 = executor.rpc("open_exec_claim", {"p_worker": "x2"})
    assert ex2["run_id"] == rid
    assert service.rpc("open_finish", {"p_run": rid, "p_worker": "e2", "p_attempt": att + 1, "p_status": "done", "p_total": 1.0, "p_report": {}})[0] in (200, 204)
    drain(service, executor, "post")


def test_hidden_bundle_object_is_service_only(hs, service):
    blob = b"AOHB1" + bytes(range(64))
    st, _ = service.upload("open-private", "hidden-test.bundle", blob)
    assert st in (200, 201), _
    from worker.supa import Supa
    from harness import service_key
    assert Supa(hs.url, service_key()).download("open-private", "hidden-test.bundle") == blob
    c, _ = user(hs)
    st, _ = c.download("open-private", "hidden-test.bundle")
    assert st >= 400
    st, _ = Client(hs.url).download("open-private", "hidden-test.bundle")
    assert st >= 400


def test_executor_auth_user_path(hs, service):
    """Asymmetric-JWT projects: the executor signs in as a listed auth user (migration 20261013000100).
    Only listed users pass the guard; the listed user still cannot act as the engine or read private tables."""
    drain(service, Client(hs.url, jwt_encode({"role": "open_executor", "exp": 4102444800})), "pre-u")
    ex, ex_uid = user(hs)
    other, _ = user(hs)
    for c in (ex, other):  # not listed yet: rejected
        assert c.rpc("open_exec_claim", {"p_worker": "u"})[0] >= 400
    with psycopg.connect(hs.db_uri, autocommit=True) as conn:
        conn.execute("insert into private.open_executor_users(user_id, note) values (%s, 'test')", (ex_uid,))
    sub, _ = user(hs)
    assert sub.rpc("open_submit", {"p_problems": ["cr_array_v5"], "p_zip_base64": agent_zip()})[0] == 200
    done = drain(service, ex, "u")
    assert done
    assert other.rpc("open_exec_claim", {"p_worker": "u2"})[0] >= 400
    for name, args in [("open_engine_claim", {"p_worker": "u"}), ("open_requeue_stale", {"p_minutes": 0})]:
        assert ex.rpc(name, args)[0] >= 400, name
    for table in ("open_submission_files", "open_run_details", "open_messages", "open_executor_users"):
        assert ex.select(table)[0] >= 400
