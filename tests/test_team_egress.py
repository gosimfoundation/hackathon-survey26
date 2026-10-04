"""Team egress: allow-listed domains only, through the pinned forwarder sidecar."""
from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from project_platform.job_client import JobError  # noqa: E402
from project_platform.team_egress import (  # noqa: E402
    checked_team_egress, render_team_proxy_script, valid_domain, valid_variable_name,
)


def test_domain_rules():
    for good in ("api.kimi.com", "generativelanguage.googleapis.com", "api.deepseek.com", "a-b.example.org"):
        assert valid_domain(good), good
    for bad in ("localhost", "127.0.0.1", "10.0.0.1", "api", "API.KIMI.COM", "a..b", "-a.com", "x.local",
                "svc.internal", "host.lan", "[::1]", "api.kimi.com:443", "https://api.kimi.com", "x.onion",
                "a.home.arpa", "", None, 7):
        assert not valid_domain(bad), bad


def test_variable_names():
    for good in ("OPENAI_API_KEY", "KIMI_KEY", "A", "MY_MODEL_2"):
        assert valid_variable_name(good)
    for bad in ("openai", "1KEY", "OBSERVER_RUN_TOKEN", "SAC_X", "HTTPS_PROXY", "https_proxy", "PATH",
                "LD_PRELOAD", "FTP_PROXY", "A" * 65, "A-B"):
        assert not valid_variable_name(bad), bad


def test_payload_validation():
    good = {"environment": {"OPENAI_API_KEY": "sk-1", "OPENAI_MODEL": "k3"}, "secrets": ["OPENAI_API_KEY"],
            "domains": ["api.kimi.com"]}
    assert checked_team_egress(good) == good
    for bad in (None, {}, {**good, "extra": 1}, {**good, "domains": ["127.0.0.1"]},
                {**good, "domains": ["a.com"] * 2}, {**good, "domains": [f"d{i}.com" for i in range(11)]},
                {**good, "secrets": ["MISSING"]}, {**good, "environment": {"PATH": "/x"}},
                {**good, "environment": {"K": "x" * 8193}}, {**good, "environment": {"K": 1}},
                {**good, "environment": {f"K{i}": "v" for i in range(21)}}):
        with pytest.raises(JobError):
            checked_team_egress(bad)


# --- the sidecar script itself, run as a local process -----------------------------------

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def tls_stub(tmp_path_factory):
    """A TLS server on loopback that answers "HELLO <server name>" to any request."""
    if not shutil.which("openssl"):
        pytest.skip("openssl is required for the TLS stub")
    root = tmp_path_factory.mktemp("tls")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=stub",
                    "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem")],
                   check=True, capture_output=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / "cert.pem", root / "key.pem")
    names: list[str] = []
    context.sni_callback = lambda sock, name, ctx: names.append(name)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)

    def serve():
        while True:
            try:
                raw, _ = listener.accept()
            except OSError:
                return
            try:
                with context.wrap_socket(raw, server_side=True) as conn:
                    conn.recv(4096)
                    conn.sendall(b"HELLO " + (names[-1] if names else "").encode())
            except (OSError, ssl.SSLError):
                pass
    threading.Thread(target=serve, daemon=True).start()
    yield listener.getsockname()[1], names
    listener.close()


@pytest.fixture(scope="module")
def sidecar(tls_stub):
    port, _ = tls_stub
    connect_port, tls_port = _free_port(), _free_port()
    script = render_team_proxy_script(
        ["allowed.test", "private.test", "rebind.test", "nowhere.test"], connect_port=connect_port,
        tls_port=tls_port, test_port=port,
        test_hosts={"allowed.test": ["127.0.0.1"], "other.test": ["127.0.0.1"], "private.test": ["10.0.0.5"],
                    "rebind.test": ["127.0.0.1", "192.168.0.2"], "metadata.test": ["169.254.169.254"]})
    process = subprocess.Popen([sys.executable, "-u", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    process.stdin.write(script)
    process.stdin.close()
    assert process.stdout.readline().strip() == b"READY"
    yield connect_port, tls_port
    process.kill()
    process.wait()


def _client_context():
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _via_connect(connect_port: int, target: str) -> tuple[bytes, bytes]:
    with socket.create_connection(("127.0.0.1", connect_port), timeout=10) as raw:
        raw.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = raw.recv(1024)
            if not chunk:
                break
            head += chunk
        status = head.split(b"\r\n", 1)[0]
        if b" 200 " not in status:
            return status, b""
        host = target.rsplit(":", 1)[0]
        with _client_context().wrap_socket(raw, server_hostname=host) as tls:
            tls.sendall(b"GET / HTTP/1.1\r\n\r\n")
            return status, tls.recv(1024)


def _via_tls(tls_port: int, name: str) -> bytes:
    with socket.create_connection(("127.0.0.1", tls_port), timeout=10) as raw:
        with _client_context().wrap_socket(raw, server_hostname=name) as tls:
            tls.sendall(b"GET / HTTP/1.1\r\n\r\n")
            return tls.recv(1024)


def test_connect_reaches_only_allowed_public_domains(sidecar):
    connect_port, _ = sidecar
    status, body = _via_connect(connect_port, "allowed.test:443")
    assert b" 200 " in status and body == b"HELLO allowed.test"
    for target in ("other.test:443",          # not on the team's list
                   "allowed.test:80",          # only port 443
                   "allowed.test:22",
                   "127.0.0.1:443",            # IP literal
                   "private.test:443",         # resolves to a private address
                   "rebind.test:443",          # one of its addresses is private
                   "metadata.test:443"):
        assert b" 403 " in _via_connect(connect_port, target)[0], target
    # Anything but CONNECT is refused.
    with socket.create_connection(("127.0.0.1", connect_port), timeout=10) as raw:
        raw.sendall(b"GET http://allowed.test/ HTTP/1.1\r\nHost: allowed.test\r\n\r\n")
        assert b" 403 " in raw.recv(1024)


def test_direct_tls_is_spliced_by_server_name(sidecar):
    _, tls_port = sidecar
    assert _via_tls(tls_port, "allowed.test") == b"HELLO allowed.test"
    for name in ("other.test", "private.test", "rebind.test"):
        with pytest.raises((ssl.SSLError, OSError)):
            _via_tls(tls_port, name)
    # Plain bytes that are not a TLS ClientHello are dropped.
    with socket.create_connection(("127.0.0.1", tls_port), timeout=10) as raw:
        raw.sendall(b"GET / HTTP/1.1\r\n\r\n")
        raw.settimeout(5)
        try:
            assert raw.recv(1024) == b""
        except ConnectionResetError:
            pass


def test_production_script_never_carries_test_settings():
    script = render_team_proxy_script(["api.kimi.com"]).decode()
    assert 'TEST_HOSTS, TEST_PORT = {}, 0' in script and '["api.kimi.com"]' in script
    with pytest.raises(JobError):
        render_team_proxy_script(["allowed.test"])
    with pytest.raises(JobError):
        render_team_proxy_script(["10.0.0.1"])


# --- real Docker: a container on the internal network --------------------------------------

def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="Docker is required")
def test_docker_participant_reaches_only_allowed_domains():
    """Real network: an allowed public domain works both ways (proxy and direct TLS);
    any other domain, an IP literal and the bridge are unreachable."""
    import os
    from project_platform.egress import PROXY_IMAGE
    from project_platform.team_egress import TeamEgress
    env = {k: os.environ[k] for k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG")
           if k in os.environ}
    egress = TeamEgress(["api.github.com"], client_env=env)
    probe = r"""
import json, os, socket, ssl, urllib.request
out = {}
def get(url):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status
    except Exception as e:
        return type(e).__name__
out["proxy_allowed"] = get("https://api.github.com/zen")
out["proxy_other"] = get("https://www.google.com/")
for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
    os.environ.pop(k, None)
out["direct_allowed"] = get("https://api.github.com/zen")
out["direct_other"] = get("https://www.google.com/")
try:
    socket.create_connection(("1.1.1.1", 443), timeout=5).close(); out["ip"] = "open"
except OSError as e:
    out["ip"] = "blocked"
print(json.dumps(out))
"""
    try:
        egress.start()
        command = ["docker", "run", "--rm", "--network", egress.network, "--cap-drop=ALL", "--user", "65534:65534"]
        for host in egress.hosts:
            command += ["--add-host", host]
        for key, value in egress.environment.items():
            command += ["-e", f"{key}={value}"]
        result = subprocess.run(command + ["--entrypoint", "python3", PROXY_IMAGE, "-c", probe],
                                capture_output=True, text=True, timeout=180, env=env)
        assert result.returncode == 0, result.stderr + egress.log
        import json
        out = json.loads(result.stdout.strip().splitlines()[-1])
        assert out["proxy_allowed"] == 200 and out["direct_allowed"] == 200, out
        assert out["proxy_other"] != 200 and out["direct_other"] != 200 and out["ip"] == "blocked", out
    finally:
        egress.close()
    names = subprocess.run(["docker", "network", "ls", "--format", "{{.Name}}"], capture_output=True, text=True,
                           env=env).stdout
    assert egress.network not in names


# --- job wiring -----------------------------------------------------------------------------

TEAM = {"environment": {"OPENAI_API_KEY": "sk-team-secret-1234", "OPENAI_BASE_URL": "https://api.kimi.com/coding/v1",
                        "OPENAI_MODEL": "k3"},
        "secrets": ["OPENAI_API_KEY"], "domains": ["api.kimi.com", "api.deepseek.com"]}


def _fake_egress(events):
    class Egress:
        network = "observer-egress-" + "1" * 32
        environment = {"HTTPS_PROXY": "http://172.30.0.2:3128", "https_proxy": "http://172.30.0.2:3128"}

        def __init__(self, domains, *, client_env):
            events.append(("team-egress", tuple(domains)))
            self.hosts = [f"{d}:172.30.0.2" for d in domains]

        def pull(self):
            events.append("forwarder-pull")

        def start(self):
            events.append("forwarder-start")
            return self

        def close(self):
            events.append("forwarder-close")
    return Egress


def test_engine_job_injects_team_variables_and_joins_only_the_team_network(monkeypatch, tmp_path):
    import uuid
    from project_platform import job_runner
    from project_platform.docker_runtime import DockerWorkspace

    events, started = [], {}

    class Stop(Exception):
        pass

    real_start = DockerWorkspace.start

    def start(self, environment, **kwargs):
        transport = real_start(self, environment, **kwargs)
        started.update(env={k: v for k, v in transport.environment.items()} if hasattr(transport, "environment")
                       else {}, command=list(transport.command) if hasattr(transport, "command") else [],
                       redactions=getattr(transport, "redactions", None), kwargs=kwargs)
        raise Stop()

    run = str(uuid.uuid4())
    manifest = {"schema_version": "observer-project-v1", "image": "python@sha256:" + "e" * 64, "run": ["python3"],
                "environment": {"OPENAI_MODEL": "manifest-default", "OTHER": "1"}}
    participant = {"run_credential": f"obs_{run}." + "p" * 43, "model_base_url": "https://platform.test/m/v1",
                   "source_digest": "d" * 64, "manifest": manifest}
    (tmp_path / "project").mkdir()
    monkeypatch.setattr(job_runner, "TeamEgress", _fake_egress(events))
    monkeypatch.setattr(job_runner, "RestrictedEgress", lambda *a, **k: pytest.fail("model proxy egress used"))
    monkeypatch.setattr(job_runner, "_participant_runtime", lambda payload, p, root, http, sealed=None: (
        DockerWorkspace(tmp_path / "project", job_runner.ProjectManifest.parse(manifest), manifest["image"]),
        {"OBSERVER_API_URL": "https://platform.test/s", "OBSERVER_RUN_TOKEN": p["run_credential"],
         "OBSERVER_RUN_ID": run, "OPENAI_BASE_URL": p["model_base_url"], "OPENAI_API_KEY": p["run_credential"],
         "ANTHROPIC_BASE_URL": "https://platform.test/m", "ANTHROPIC_API_KEY": p["run_credential"]}))
    monkeypatch.setattr(job_runner, "download_project", lambda *a: ())
    monkeypatch.setattr(job_runner, "extract_project", lambda files, root: root.mkdir(parents=True))
    monkeypatch.setattr(job_runner, "is_v4_bundle", lambda root: True)
    monkeypatch.setattr(DockerWorkspace, "pull", lambda self: events.append("pull"))
    monkeypatch.setattr(DockerWorkspace, "build", lambda self: events.append("build"))
    monkeypatch.setattr(DockerWorkspace, "start", start)
    payload = {"run_id": run, "run_credential": f"obs_{run}." + "e" * 43, "session_url": "https://platform.test/s",
               "scenario_url": "https://platform.test/c", "scenario_digest": "c" * 64, "runtime_seconds": 900,
               "archive_url": "https://platform.test/a", "colocated": participant, "restricted_egress": True,
               "team_egress": TEAM}
    with pytest.raises(job_runner.ProjectJobFailure):
        job_runner.engine_job(payload, tmp_path, job_runner.Http(local=False))
    assert events[0] == ("team-egress", ("api.kimi.com", "api.deepseek.com"))
    assert events[-2:] == ["forwarder-start", "forwarder-close"]
    assert started["kwargs"]["hosts"] == ("api.kimi.com:172.30.0.2", "api.deepseek.com:172.30.0.2")
    env = started["env"]
    # The team's variables, the run identity and the proxy; never the platform model proxy.
    assert env["OPENAI_API_KEY"] == "sk-team-secret-1234" and env["OPENAI_BASE_URL"] == "https://api.kimi.com/coding/v1"
    assert env["OPENAI_MODEL"] == "k3" and env["HTTPS_PROXY"] == "http://172.30.0.2:3128"
    assert "ANTHROPIC_BASE_URL" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["OBSERVER_RUN_TOKEN"] == participant["run_credential"]
    command = started["command"]
    assert command[command.index("--network") + 1] == "observer-egress-" + "1" * 32
    assert "sk-team-secret-1234" in started["redactions"]


def test_docker_start_merges_team_variables_over_the_manifest_and_redacts_secrets(tmp_path):
    from project_platform.docker_runtime import DockerWorkspace
    from project_platform.manifest import ProjectManifest, ProjectError
    manifest = {"schema_version": "observer-project-v1", "image": "python@sha256:" + "e" * 64, "run": ["python3"],
                "environment": {"OPENAI_MODEL": "manifest-default", "OTHER": "1"}}
    (tmp_path / "p").mkdir()
    runtime = DockerWorkspace(tmp_path / "p", ProjectManifest.parse(manifest), manifest["image"])
    runtime.network = "observer-egress-" + "1" * 32
    run_env = {"OBSERVER_API_URL": "https://platform.test/s", "OBSERVER_RUN_TOKEN": "obs_x.tok",
               "OBSERVER_RUN_ID": "r", "HTTPS_PROXY": "http://172.30.0.2:3128"}
    transport = runtime.start(run_env, team=TEAM, hosts=("api.kimi.com:172.30.0.2",))
    command = transport.command
    assert "sk-team-secret-1234" in transport.redactions
    assert "--add-host" in command and "api.kimi.com:172.30.0.2" in command
    env = transport.environment
    assert env["OPENAI_MODEL"] == "k3" and env["OTHER"] == "1" and env["OPENAI_API_KEY"] == "sk-team-secret-1234"
    assert env["HTTPS_PROXY"] == "http://172.30.0.2:3128"
    # Values travel by name (docker --env NAME), never on the command line.
    assert "sk-team-secret-1234" not in " ".join(command)
    # Proxy variables and host entries are refused outside team egress.
    with pytest.raises(ProjectError):
        runtime.start(run_env)
    runtime.network = None
    with pytest.raises(ProjectError):
        runtime.start({k: v for k, v in run_env.items() if k != "HTTPS_PROXY"}, team=TEAM,
                      hosts=("api.kimi.com:172.30.0.2",))
