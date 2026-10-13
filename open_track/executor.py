"""Executor for the open track: runs participant agents, never sees hidden seeds or wording pools.

For each run the engine has started: unpack the submission ZIP, start a metered model proxy container
(participant's own API; the key is decrypted here and passed only to the proxy) and the agent container
(no network except an internal one shared with the proxy, read-only files, non-root, CPU/memory/PID
limits), then relay protocol lines between the agent's stdin/stdout and the database. At the end the
proxy's ledger (model usage) and the agent's stderr tail are reported to the engine.

    python -m open_track.executor --max-seconds 19800
Env: SUPABASE_URL, SUPABASE_ANON_KEY, OPEN_EXECUTOR_TOKEN (a JWT with role=open_executor: this machine never
holds the service key), OPEN_TRACK_KEY_PRIVATE (PEM; needed for model submissions),
OPEN_AGENT_IMAGE (default python:3.12-slim; pin a digest in production), OPEN_WORKER_ID, DOCKER (binary),
OPEN_WORK_DIR (where run folders go; must be visible to the Docker daemon).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from worker.supa import SupabaseError

from open_track import crypto

HERE = Path(__file__).resolve().parent
AOHKIT = HERE / "problems" / "aohkit"
IMAGE = os.environ.get("OPEN_AGENT_IMAGE", "python:3.12-slim")
DOCKER = os.environ.get("DOCKER", "docker")
POLL = float(os.environ.get("OPEN_POLL_SECONDS", "0.05"))
# Resolvers for the model proxy only (Docker's embedded DNS may have no upstream on some hosts); '' = Docker's default.
PROXY_DNS = [x for x in os.environ.get("OPEN_PROXY_DNS", "1.1.1.1,8.8.8.8").split(",") if x.strip()]
MAX_UNZIPPED = 20 * 1024 * 1024
MAX_LINE = 512 * 1024
LOG_TAIL = 64 * 1024
FINISH_GRACE = 10
MAX_RUN_SECONDS = float(os.environ.get("OPEN_MAX_RUN_SECONDS", "7200"))  # hard stop whatever the engine does
ALIVE_EVERY = 5.0


class BadSubmission(RuntimeError):
    pass


class ExecClient:
    """PostgREST RPC as the open_executor role (anon key at the gateway, executor JWT as the identity)."""

    def __init__(self, url: str, anon_key: str, token: str, timeout: float = 60):
        self.url, self.anon, self.token, self.timeout = url.rstrip("/"), anon_key, token, timeout

    def rpc(self, name: str, args: dict):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"{self.url}/rest/v1/rpc/{name}", data=json.dumps(args).encode(), method="POST",
                                     headers={"apikey": self.anon, "Authorization": f"Bearer {self.token}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                out = r.read()
                return json.loads(out) if out else None
        except urllib.error.HTTPError as exc:
            raise SupabaseError(exc.code, exc.read().decode("utf-8", "replace"), req.full_url) from exc


def unpack(zip_b64: str, sha256: str, dest: Path) -> None:
    data = base64.b64decode(zip_b64)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise BadSubmission("ZIP checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_UNZIPPED or len(infos) > 2000:
            raise BadSubmission("ZIP too large when unpacked (20 MB / 2000 files)")
        names = [i.filename for i in infos]
        for i in infos:
            mode = (i.external_attr >> 16) & 0o170000
            if i.filename.startswith("/") or ".." in Path(i.filename).parts or mode == 0o120000:
                raise BadSubmission(f"unsafe path in ZIP: {i.filename}")
        prefix = ""
        if "agent.py" not in names:
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) == 1 and f"{next(iter(tops))}/agent.py" in names:
                prefix = next(iter(tops)) + "/"
            else:
                raise BadSubmission("agent.py must be at the ZIP root")
        written = 0
        for i in infos:
            if i.is_dir() or not i.filename.startswith(prefix):
                continue
            target = dest / i.filename[len(prefix):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, open(target, "wb") as out:
                while True:  # count what is really written: declared sizes in a ZIP can lie
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UNZIPPED:
                        raise BadSubmission("ZIP too large when unpacked (20 MB)")
                    out.write(chunk)
    for p in [dest, *dest.rglob("*")]:
        p.chmod(0o755 if p.is_dir() else 0o644)


def docker(*args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=timeout, check=check)


class Run:
    def __init__(self, supa: ExecClient, job: dict, private_pem: str):
        self.supa, self.job, self.private_pem = supa, job, private_pem
        self.id = job["run_id"]
        self.tag = "aoh-" + uuid.uuid4().hex[:12]
        self.work = Path(tempfile.mkdtemp(prefix="aoh-exec-", dir=os.environ.get("OPEN_WORK_DIR") or None))
        self.out_seq = 0
        self.lock = threading.Lock()
        self.worker = job.get("_worker", "")
        self.attempt = int(job.get("attempt", 0))
        self.log_tail = bytearray()

    # ------------------------------------------------------------ database
    def post(self, direction: str, body: dict, seq: int | None = None) -> None:
        with self.lock:
            if seq is None:
                self.out_seq += 1
                seq = self.out_seq
        for attempt in range(4):
            try:
                self.supa.rpc("open_exec_post", {"p_run": self.id, "p_worker": self.worker, "p_attempt": self.attempt,
                                                 "p_direction": direction, "p_seq": seq, "p_body": body})
                return
            except SupabaseError as exc:
                if "run_not_owned" in exc.body or attempt == 3:
                    raise
                time.sleep(0.5 * (attempt + 1))

    # ------------------------------------------------------------ containers
    def start_proxy(self, model_key: str) -> None:
        ledger = self.work / "ledger"
        ledger.mkdir()
        ledger.chmod(0o777)
        docker("network", "create", "--internal", self.tag)
        # the proxy's own way out: a separate ordinary bridge (Docker's embedded DNS does not resolve
        # outside names for a container whose networks are all internal or the default bridge)
        docker("network", "create", self.tag + "-out")
        env = ["-e", f"OPEN_MODEL_BASE={self.job.get('model_base') or ''}", "-e", f"OPEN_MODEL_NAME={self.job.get('model_name') or ''}",
               "-e", "OPEN_MODEL_KEY", "-e", "OPEN_LEDGER=/ledger/ledger.jsonl"]
        # the key goes through the docker client's environment, never onto the command line
        dns = [a for d in PROXY_DNS for a in ("--dns", d.strip())]
        subprocess.run([DOCKER, "run", "-d", "--rm", "--name", self.tag + "-llm", "--network", self.tag + "-out", *dns,
                        "--memory", "256m", "--cpus", "0.5",
                        "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                        "--tmpfs", "/tmp:size=16m", "-v", f"{HERE / 'model_proxy.py'}:/proxy/model_proxy.py:ro",
                        "-v", f"{ledger}:/ledger", *env, IMAGE, "python3", "-u", "/proxy/model_proxy.py"],
                       env={**os.environ, "OPEN_MODEL_KEY": model_key}, capture_output=True, text=True, timeout=300, check=True)
        docker("network", "connect", "--alias", "llm", self.tag, self.tag + "-llm")
        probe = "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/',timeout=2)"
        for _ in range(60):  # the agent must not start before the proxy listens
            if docker("exec", self.tag + "-llm", "python3", "-c", probe, check=False, timeout=30).returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError("model proxy did not start")

    def agent_command(self) -> list[str]:
        return [DOCKER, "run", "-i", "--rm", "--name", self.tag + "-agent", "--network", self.tag,
                "--read-only", "--tmpfs", "/tmp:size=64m", "--memory", "1g", "--cpus", "1", "--pids-limit", "128",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
                "-v", f"{self.work / 'agent'}:/agent:ro", "-v", f"{AOHKIT}:/aoh/aohkit:ro", "-w", "/agent",
                "-e", "HOME=/tmp", "-e", "TMPDIR=/tmp", "-e", "PYTHONPATH=/aoh", "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "PYTHONUNBUFFERED=1", "-e", "AOH_LLM_PROXY=http://llm:8080/ask",
                IMAGE, "python3", "agent.py"]

    def cleanup(self) -> None:
        for args in (("kill", self.tag + "-agent"), ("stop", "-t", "2", self.tag + "-llm"), ("network", "rm", self.tag), ("network", "rm", self.tag + "-out")):
            try:
                docker(*args, check=False, timeout=60)
            except subprocess.TimeoutExpired:
                pass

    # ------------------------------------------------------------ relay
    def execute(self) -> None:
        job = self.job
        try:
            (self.work / "agent").mkdir()
            unpack(job["zip_base64"], job["zip_sha256"], self.work / "agent")
            key = ""
            if job.get("uses_model"):
                if not self.private_pem:
                    raise BadSubmission("this executor cannot decrypt model keys")
                key = crypto.decrypt_model_key(job.get("key_ciphertext") or "", self.private_pem)
            self.start_proxy(key)
            proc = subprocess.Popen(self.agent_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0)
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) if isinstance(exc, BadSubmission) else f"{type(exc).__name__}"
            self.post("from_agent", {"message_type": "executor_failed", "reason": reason})
            self.cleanup()
            return
        try:
            self.post("from_agent", {"message_type": "executor_ready"})
        except SupabaseError:  # the engine gave the run up meanwhile: stop quietly
            proc.kill()
            self.cleanup()
            return
        finished = threading.Event()
        state = {"expected": None}  # sequence of the decision the agent owes; anything else is dropped

        def pump_stderr():  # keep only the tail in memory: an agent cannot fill the disk through stderr
            for chunk in iter(lambda: proc.stderr.read(8192), b""):
                self.log_tail += chunk
                if len(self.log_tail) > LOG_TAIL:
                    del self.log_tail[:len(self.log_tail) - LOG_TAIL]

        def pump_stdout():
            for raw in iter(lambda: proc.stdout.readline(MAX_LINE + 1), b""):  # bounded: no unbounded line buffering
                if len(raw) > MAX_LINE:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue  # stdout noise is ignored, like the local runner
                if (isinstance(msg, dict) and msg.get("message_type") == "decision_response"
                        and state["expected"] is not None and msg.get("decision_sequence") == state["expected"]):
                    state["expected"] = None  # one answer per request: floods never reach the database
                    try:
                        self.post("from_agent", msg)
                    except SupabaseError:
                        break
            if not finished.is_set():
                try:
                    self.post("from_agent", {"message_type": "agent_exited"})
                except SupabaseError:
                    pass

        reader = threading.Thread(target=pump_stdout, daemon=True)
        reader.start()
        threading.Thread(target=pump_stderr, daemon=True).start()
        after = 0
        started = last_alive = time.time()
        try:
            while not finished.is_set():
                if time.time() - started > MAX_RUN_SECONDS:
                    break
                if time.time() - last_alive > ALIVE_EVERY:
                    last_alive = time.time()
                    if not self.supa.rpc("open_exec_alive", {"p_run": self.id, "p_worker": self.worker, "p_attempt": self.attempt}):
                        break  # requeued, finished or failed elsewhere: stop this agent
                rows = self.supa.rpc("open_exec_fetch", {"p_run": self.id, "p_worker": self.worker, "p_attempt": self.attempt,
                                                         "p_after": after}) or []
                for row in rows:
                    after = row["seq"]
                    body = row["body"]
                    if body.get("message_type") == "finished":
                        finished.set()
                    elif body.get("message_type") == "decision_request":
                        state["expected"] = body.get("decision_sequence")
                    try:
                        proc.stdin.write((json.dumps(body, separators=(",", ":")) + "\n").encode())
                        proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                if not rows:
                    time.sleep(POLL)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=FINISH_GRACE)
            except subprocess.TimeoutExpired:
                docker("kill", self.tag + "-agent", check=False)
                proc.wait(timeout=30)
            reader.join(timeout=5)
            usage = {"calls": 0, "tokens_in": 0, "tokens_out": 0}
            ledger = self.work / "ledger" / "ledger.jsonl"
            if ledger.exists():
                for line in ledger.read_text().splitlines():
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    usage["calls"] += 1
                    usage["tokens_in"] += int(r.get("in", 0))
                    usage["tokens_out"] += int(r.get("out", 0))
            log = bytes(self.log_tail).decode("utf-8", "replace")
            (self.work / "agent_stderr.log").write_text(log)
            try:  # report before tearing the containers down: the engine is waiting for it
                self.post("usage", {**usage, "agent_log": log}, seq=1)
            except SupabaseError:
                pass
            self.cleanup()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-seconds", type=float, default=19800)
    ap.add_argument("--once", action="store_true", help="exit once no run has appeared for --idle-seconds")
    ap.add_argument("--idle-seconds", type=float, default=0)
    a = ap.parse_args(argv)
    supa = ExecClient(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"], os.environ["OPEN_EXECUTOR_TOKEN"])
    pem = os.environ.get("OPEN_TRACK_KEY_PRIVATE", "")
    worker = os.environ.get("OPEN_WORKER_ID", f"exec-{os.getpid()}")
    docker("pull", IMAGE, check=False, timeout=600)
    end = time.time() + a.max_seconds
    last = time.time()
    while time.time() < end:
        job = supa.rpc("open_exec_claim", {"p_worker": worker})
        if not job:
            if a.once and time.time() - last > a.idle_seconds:
                return
            time.sleep(1)
            continue
        try:
            Run(supa, {**job, "_worker": worker}, pem).execute()
        except Exception as exc:  # noqa: BLE001 - one broken run must not stop the queue
            print(f"{job.get('run_id')}: executor error {type(exc).__name__}: {exc}", flush=True)
        last = time.time()


if __name__ == "__main__":
    main()
