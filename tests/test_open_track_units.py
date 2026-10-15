"""Open track building blocks: key handling, hidden bundle, ZIP safety, model metering, report privacy,
and (with Docker) the agent container's network isolation."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from open_track import crypto  # noqa: E402
from open_track.engine import public_summary  # noqa: E402
from open_track.executor import BadSubmission, unpack  # noqa: E402


def zip_b64(files: dict[str, bytes], symlink: str | None = None) -> tuple[str, str]:
    import hashlib
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    raw = buf.getvalue()
    return base64.b64encode(raw).decode(), hashlib.sha256(raw).hexdigest()


def test_model_key_round_trip_and_wrong_key(tmp_path):
    crypto.keygen(str(tmp_path / "a"))
    crypto.keygen(str(tmp_path / "b"))
    ct = crypto.encrypt_model_key("sk-secret-123", (tmp_path / "a" / "public.pem").read_text())
    assert crypto.decrypt_model_key(ct, (tmp_path / "a" / "private.pem").read_text()) == "sk-secret-123"
    with pytest.raises(Exception):
        crypto.decrypt_model_key(ct, (tmp_path / "b" / "private.pem").read_text())
    with pytest.raises(SystemExit):
        crypto.keygen(str(tmp_path / "a"))  # never overwrites a key pair


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_webcrypto_encryption_decrypts_in_the_executor(tmp_path):
    crypto.keygen(str(tmp_path / "k"))
    jwk = (tmp_path / "k" / "public.jwk.json").read_text()
    js = (
        "const jwk=JSON.parse(process.argv[1]);"
        "const k=await crypto.subtle.importKey('jwk',jwk,{name:'RSA-OAEP',hash:'SHA-256'},false,['encrypt']);"
        "const ct=await crypto.subtle.encrypt({name:'RSA-OAEP'},k,new TextEncoder().encode('sk-from-browser'));"
        "console.log(Buffer.from(ct).toString('base64'));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", js, jwk], capture_output=True, text=True, check=True).stdout.strip()
    assert crypto.decrypt_model_key(out, (tmp_path / "k" / "private.pem").read_text()) == "sk-from-browser"


def test_hidden_bundle_seal_and_extract(tmp_path):
    src = tmp_path / "src"
    (src / "_hidden" / "nl").mkdir(parents=True)
    (src / "_hidden" / "salt.txt").write_text("s3cret\n")
    for name in crypto.HIDDEN_POOLS:
        (src / "_hidden" / "nl" / f"{name}.v1.json").write_text(json.dumps({"name": name}))
        (src / "_hidden" / "nl" / f"{name}.json").write_text("{}")
        (src / "_hidden" / "nl" / f"{name}.json.selected").write_text(f"{name}.v1.json")
    key = base64.b64encode(os.urandom(32)).decode()
    blob = crypto.seal(crypto.pack_hidden(str(src)), key)
    assert b"s3cret" not in blob
    dest = tmp_path / "dest"
    crypto.extract_hidden(blob, key, str(dest))
    assert (dest / "_hidden" / "salt.txt").read_text() == "s3cret\n"
    assert json.loads((dest / "_hidden" / "nl" / "cr_array_v5.json").read_text()) == {"name": "cr_array_v5"}
    assert not list((dest / "_hidden" / "nl").glob("*.selected"))
    with pytest.raises(Exception):
        crypto.extract_hidden(blob, base64.b64encode(os.urandom(32)).decode(), str(dest))
    # a bundle may only contain _hidden/...
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        crypto.extract_hidden(crypto.seal(evil.getvalue(), key), key, str(dest))


def test_zip_rules(tmp_path):
    b64, sha = zip_b64({"agent.py": b"print(1)", "lib/x.py": b"y=1"})
    unpack(b64, sha, tmp_path / "a")
    assert (tmp_path / "a" / "agent.py").read_bytes() == b"print(1)" and (tmp_path / "a" / "lib" / "x.py").exists()
    b64, sha = zip_b64({"myagent/agent.py": b"print(2)"})
    unpack(b64, sha, tmp_path / "b")
    assert (tmp_path / "b" / "agent.py").read_bytes() == b"print(2)"
    for files, link in (({"../evil.py": b"x", "agent.py": b""}, None), ({"x.py": b""}, None), ({"agent.py": b""}, "link")):
        b64, sha = zip_b64(files, link)
        with pytest.raises(BadSubmission):
            unpack(b64, sha, tmp_path / "c")
    b64, _ = zip_b64({"agent.py": b""})
    with pytest.raises(BadSubmission):
        unpack(b64, "0" * 64, tmp_path / "d")


def test_public_summary_keeps_numbers_only():
    report = {"total": 12.5, "correct_points": 10, "reports": [{"candidate": "C1", "result": "correct"}],
              "status": "ok", "decisions": 144, "llm": {"calls": 1}, "events": {"fault_at": 33}, "flag": True}
    out = public_summary(report)
    assert out["total"] == 12.5 and out["correct_points"] == 10 and out["llm"] == {"calls": 1}
    assert "reports" not in out and "events" not in out


class FakeUpstream(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeUpstream.seen.append((self.headers.get("Authorization"), body))
        data = json.dumps({"choices": [{"message": {"content": "pong"}}],
                           "usage": {"prompt_tokens": 11, "completion_tokens": 3}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def ask(port: int) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"prompt": "ping", "max_tokens": 9}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as r:
        return json.loads(r.read())


def start_proxy(tmp_path, port, key, cap="2"):
    env = {**os.environ, "OPEN_MODEL_BASE": f"http://127.0.0.1:{FakeUpstream.port}/v1", "OPEN_MODEL_NAME": "m-1",
           "OPEN_MODEL_KEY": key, "OPEN_LEDGER": str(tmp_path / "ledger.jsonl"), "OPEN_MAX_CALLS": cap, "OPEN_PORT": str(port)}
    p = subprocess.Popen([sys.executable, str(ROOT / "open_track" / "model_proxy.py")], env=env)
    for _ in range(100):
        try:
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{port}/", timeout=1)
            return p
        except Exception:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("proxy did not start")


def test_model_proxy_meters_caps_and_never_leaks_the_key(tmp_path):
    FakeUpstream.port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", FakeUpstream.port), FakeUpstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = free_port()
    p = start_proxy(tmp_path, port, "sk-participant")
    try:
        assert ask(port) == {"text": "pong"}
        assert ask(port) == {"text": "pong"}
        third = ask(port)
        assert "cap" in third["error"]
        auth, body = FakeUpstream.seen[0]
        assert auth == "Bearer sk-participant" and body["model"] == "m-1" and body["max_tokens"] == 9
        lines = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
        assert [(x["in"], x["out"]) for x in lines] == [(11, 3), (11, 3)]
    finally:
        p.kill()
    # no key: every call refused, nothing metered
    port2 = free_port()
    (tmp_path / "n").mkdir()
    p = start_proxy(tmp_path / "n", port2, "")
    try:
        assert "no model" in ask(port2)["error"]
        assert (tmp_path / "n" / "ledger.jsonl").read_text() == ""
    finally:
        p.kill()
        srv.shutdown()


def docker_ok() -> bool:
    exe = os.environ.get("DOCKER", "docker")
    return bool(shutil.which(exe)) and subprocess.run([exe, "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not docker_ok(), reason="Docker not available")
def test_agent_container_reaches_only_the_model_proxy(tmp_path):
    """The agent's network: the proxy alias 'llm' answers; the internet and the host do not."""
    from open_track.executor import Run
    work = Path(os.environ.get("OPEN_WORK_DIR") or tmp_path)
    run = Run.__new__(Run)
    run.job = {"model_base": "", "model_name": ""}
    run.tag = "aoh-test-" + os.urandom(4).hex()
    import tempfile
    run.work = Path(tempfile.mkdtemp(prefix="aoh-iso-", dir=str(work)))
    (run.work / "agent").mkdir()
    probe = (
        "import urllib.request,json,socket\n"
        "o=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
        "r={}\n"
        "r['llm']=json.loads(o.open('http://llm:8080/',timeout=5).read())\n"
        "for name,url in [('internet','https://example.com/'),('ip','http://1.1.1.1/')]:\n"
        "    try:\n"
        "        o.open(url,timeout=5); r[name]='reached'\n"
        "    except Exception as e: r[name]='blocked'\n"
        "try:\n"
        "    open('/agent/x','w'); r['write']='allowed'\n"
        "except OSError: r['write']='denied'\n"
        "print(json.dumps(r))\n"
    )
    (run.work / "agent" / "agent.py").write_text(probe)
    for p in [run.work, run.work / "agent", run.work / "agent" / "agent.py"]:
        p.chmod(0o755 if p.is_dir() else 0o644)
    try:
        run.start_proxy("")
        out = subprocess.run(run.agent_command(), capture_output=True, text=True, timeout=120)
        result = json.loads(out.stdout.strip().splitlines()[-1])
        assert result == {"llm": {"ok": True}, "internet": "blocked", "ip": "blocked", "write": "denied"}, out.stderr
    finally:
        run.cleanup()


def test_migration_only_adds_open_track_objects():
    """The open-track migration may create and change only its own objects (open_* names, its bucket)."""
    import re
    sql = (ROOT / "supabase" / "migrations" / "20261013000000_open_track.sql").read_text()
    code = re.sub(r"--[^\n]*", "", sql)
    assert not re.search(r"\b(drop|truncate|alter\s+function|alter\s+policy|create\s+or\s+replace)\b", code, re.I)
    for name in re.findall(r"create\s+(?:table|view|function|index)\s+(?:if\s+not\s+exists\s+)?([\w.]+)", code, re.I):
        assert name.split(".")[-1].startswith("open_"), name
    for name in re.findall(r"alter\s+table\s+([\w.]+)", code, re.I):
        assert name.split(".")[-1].startswith("open_"), name
    for name in re.findall(r"(?<!for )\b(?:update|delete\s+from|insert\s+into)\s+([\w.]+)", code, re.I):
        assert name.split(".")[-1].startswith("open_") or name == "storage.buckets", name
    assert re.findall(r"insert into storage\.buckets\(id, name, public\) values \('([^']+)'", code) == ["open-private"]
    for name in re.findall(r"create policy (\w+) on ([\w.]+)", code):
        assert name[1].split(".")[-1].startswith("open_"), name
