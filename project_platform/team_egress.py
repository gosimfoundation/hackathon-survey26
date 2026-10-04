"""Team egress: the participant container reaches only its team's allowed domains.

The participant container joins a per-run internal Docker network (no route
anywhere). Its only neighbour is a small forwarder sidecar: trusted engine code
on a pinned image, dual-homed onto the default bridge. The sidecar accepts

* HTTPS CONNECT on port 3128 (``HTTPS_PROXY``; standard SDKs use it), and
* direct TLS on port 443: each allowed domain is mapped to the sidecar in the
  participant's ``/etc/hosts``, the sidecar reads the TLS ClientHello's server
  name and splices the connection through (clients that ignore proxy settings).

Either way only ``<allowed domain>:443`` is reachable. The sidecar resolves the
name itself, refuses it unless every address is public, and connects to one of
exactly those addresses, so a name that resolves to a private range (including
DNS rebinding) never reaches an internal service. TLS stays end to end; the
sidecar never sees plaintext or credentials. The team's variables (API keys,
base URLs, model names) are injected into the participant container as
environment variables; they never reach the sidecar.
"""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import threading
import time
import uuid

from .egress import NETWORK_PATTERN, PROXY_IMAGE
from .job_client import JobError

CONNECT_PORT = 3128
TLS_PORT = 443
MAX_DOMAINS = 10
MAX_VARIABLES = 20
MAX_VALUE_BYTES = 8192
VARIABLE_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
RESERVED_PREFIXES = ("OBSERVER_", "SAC_")
# Names the platform sets itself (proxy settings) or that would change how the
# container starts; a team cannot override them.
RESERVED_NAMES = {"HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "NODE_USE_ENV_PROXY",
                  "PATH", "HOME", "HOSTNAME", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS"}
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
DOMAIN = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(?:\.{_LABEL})+$")
RESERVED_SUFFIXES = ("localhost", "local", "internal", "intranet", "lan", "home.arpa", "arpa", "test",
                     "example", "invalid", "onion")
_DOCKER_TIMEOUT = 30
_PULL_TIMEOUT = 300


def valid_domain(value: object) -> bool:
    """A public DNS name: lowercase, at least two labels, not an IP literal or reserved name."""
    if not isinstance(value, str) or not DOMAIN.fullmatch(value):
        return False
    if re.fullmatch(r"[\d.]+", value):
        return False
    return not any(value == suffix or value.endswith("." + suffix) for suffix in RESERVED_SUFFIXES)


def valid_variable_name(name: object) -> bool:
    return (isinstance(name, str) and bool(VARIABLE_NAME.fullmatch(name)) and
            not name.startswith(RESERVED_PREFIXES) and name not in RESERVED_NAMES and
            not name.lower().endswith("_proxy"))


def checked_team_egress(value: object) -> dict:
    """The job payload's ``team_egress``: {"environment": {NAME: value}, "secrets": [NAME], "domains": [host]}."""
    if not isinstance(value, dict) or set(value) != {"environment", "secrets", "domains"}:
        raise JobError("invalid_team_egress")
    environment, secret_names, domains = value["environment"], value["secrets"], value["domains"]
    if not isinstance(environment, dict) or len(environment) > MAX_VARIABLES:
        raise JobError("invalid_team_egress")
    for name, text in environment.items():
        if (not valid_variable_name(name) or not isinstance(text, str) or "\x00" in text or
                len(text.encode()) > MAX_VALUE_BYTES):
            raise JobError("invalid_team_egress")
    if (not isinstance(secret_names, list) or any(name not in environment for name in secret_names) or
            not isinstance(domains, list) or len(domains) > MAX_DOMAINS or
            len(set(domains)) != len(domains) or not all(valid_domain(d) for d in domains)):
        raise JobError("invalid_team_egress")
    return {"environment": dict(environment), "secrets": list(secret_names), "domains": list(domains)}


# The forwarder inside the sidecar (standard library only). ALLOWED is baked in by
# the trusted engine; unit tests run this exact script in a local process.
PROXY_SCRIPT = r"""
import ipaddress, socket, sys, threading
ALLOWED = frozenset(%(allowed)s)
# Tests only: {host: [addresses]} instead of DNS, loopback allowed, and every
# connection goes to TEST_PORT. Always empty/0 in production.
TEST_HOSTS, TEST_PORT = %(test_hosts)s, %(test_port)d
CONNECT_PORT, TLS_PORT = %(connect_port)d, %(tls_port)d
IDLE, CONNECT_TIMEOUT, MAX_CONNECTIONS = 300, 15, 64
slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

def public(address):
    ip = ipaddress.ip_address(address.split("%%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if TEST_PORT and ip.is_loopback:
        return True
    return ip.is_global and not ip.is_multicast

def resolve(host):
    if TEST_PORT:
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 (a, TEST_PORT)) for a in TEST_HOSTS.get(host, [])]
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return [info for info in infos if info[0] in (socket.AF_INET, socket.AF_INET6)]

def upstream(host):
    # Resolve here and connect only to the addresses just checked: a name that
    # resolves (or later rebinds) to a private address is refused outright.
    if host not in ALLOWED:
        raise PermissionError(host)
    addresses = resolve(host)
    if not addresses or not all(public(info[4][0]) for info in addresses):
        raise PermissionError(host)
    last = None
    for family, kind, proto, _, address in addresses:
        sock = socket.socket(family, kind, proto)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            sock.connect(address)
            sock.settimeout(IDLE)
            return sock
        except OSError as error:
            last = error
            sock.close()
    raise last or OSError(host)

def pipe(source, target):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
    except OSError:
        pass
    finally:
        for sock, how in ((target, socket.SHUT_WR), (source, socket.SHUT_RD)):
            try:
                sock.shutdown(how)
            except OSError:
                pass

def splice(client, remote, first=b""):
    if first:
        remote.sendall(first)
    other = threading.Thread(target=pipe, args=(remote, client), daemon=True)
    other.start()
    pipe(client, remote)
    other.join(IDLE)

def read_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError()
        data += chunk
    return data

def server_name(hello):
    # TLS record (5 bytes) + handshake header (4) + version (2) + random (32).
    pos = 5 + 4 + 2 + 32
    pos += 1 + hello[pos]                                   # session id
    pos += 2 + int.from_bytes(hello[pos:pos + 2], "big")    # cipher suites
    pos += 1 + hello[pos]                                   # compression methods
    end = pos + 2 + int.from_bytes(hello[pos:pos + 2], "big")
    pos += 2
    while pos + 4 <= end:
        kind, size = int.from_bytes(hello[pos:pos + 2], "big"), int.from_bytes(hello[pos + 2:pos + 4], "big")
        pos += 4
        if kind == 0:                                       # server_name
            names, cursor = hello[pos + 2:pos + size], 0
            while cursor + 3 <= len(names):
                length = int.from_bytes(names[cursor + 1:cursor + 3], "big")
                if names[cursor] == 0:
                    return names[cursor + 3:cursor + 3 + length].decode("ascii").lower().rstrip(".")
                cursor += 3 + length
        pos += size
    raise ValueError("no server name")

def handle_tls(client):
    header = read_exact(client, 5)
    if header[0] != 0x16 or not 0 < int.from_bytes(header[3:5], "big") <= 16384:
        raise ValueError("not tls")
    hello = header + read_exact(client, int.from_bytes(header[3:5], "big"))
    if hello[5] != 1:
        raise ValueError("not a client hello")
    remote = upstream(server_name(hello))
    try:
        splice(client, remote, hello)
    finally:
        remote.close()

def handle_connect(client):
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = client.recv(4096)
        if not chunk or len(head) + len(chunk) > 8192:
            raise ValueError("bad request")
        head += chunk
    line = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
    if len(line) != 3 or line[0] != "CONNECT" or not line[2].startswith("HTTP/1."):
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    host, _, port = line[1].rpartition(":")
    host = host.lower().rstrip(".")
    try:
        if port != "443":
            raise PermissionError(host)
        remote = upstream(host)
    except PermissionError:
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    except OSError:
        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    try:
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        splice(client, remote, head.split(b"\r\n\r\n", 1)[1])
    finally:
        remote.close()

def serve(port, handler):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(128)
    def run(client):
        try:
            client.settimeout(IDLE)
            handler(client)
        except Exception as error:
            if isinstance(error, PermissionError):
                print("refused " + str(error)[:253], file=sys.stderr, flush=True)
        finally:
            client.close()
            slots.release()
    while True:
        client, _ = listener.accept()
        if not slots.acquire(blocking=False):
            client.close()
            continue
        threading.Thread(target=run, args=(client,), daemon=True).start()

threading.Thread(target=serve, args=(TLS_PORT, handle_tls), daemon=True).start()
threading.Thread(target=serve, args=(CONNECT_PORT, handle_connect), daemon=True).start()
print("READY", flush=True)
threading.Event().wait()
"""


def render_team_proxy_script(domains: list[str], *, connect_port: int = CONNECT_PORT, tls_port: int = TLS_PORT,
                             test_hosts: dict[str, list[str]] | None = None, test_port: int = 0) -> bytes:
    """The sidecar's exact source. ``test_hosts``/``test_port`` are for tests only:
    names resolve from that map (loopback allowed) and connections go to ``test_port``."""
    if not all(valid_domain(domain) or (test_port and domain.endswith(".test")) for domain in domains):
        raise JobError("invalid_team_egress")
    return (PROXY_SCRIPT % {"allowed": json.dumps(sorted(domains)), "test_hosts": json.dumps(test_hosts or {}),
                            "test_port": test_port, "connect_port": connect_port, "tls_port": tls_port}).encode()


class TeamEgress:
    """Per-run internal network plus the pinned allow-list forwarder."""

    def __init__(self, domains: list[str], *, client_env: dict[str, str]):
        self.domains = list(domains)
        self.client_env = dict(client_env)
        suffix = uuid.uuid4().hex
        self.network = "observer-egress-" + suffix
        self.proxy_name = "observer-proxy-" + suffix
        self.address: str | None = None
        self.process: subprocess.Popen | None = None
        self._pulled = False
        self._log = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._script = render_team_proxy_script(self.domains)

    @property
    def environment(self) -> dict[str, str]:
        """Proxy settings for the participant container (lower- and upper-case spellings)."""
        proxy = f"http://{self.address}:{CONNECT_PORT}"
        return {"HTTPS_PROXY": proxy, "https_proxy": proxy, "HTTP_PROXY": proxy, "http_proxy": proxy,
                "NO_PROXY": "", "no_proxy": "", "NODE_USE_ENV_PROXY": "1"}

    @property
    def hosts(self) -> list[str]:
        """``--add-host`` values: every allowed domain points at the sidecar."""
        return [f"{domain}:{self.address}" for domain in self.domains]

    @property
    def log(self) -> str:
        return bytes(self._log[-4096:]).decode(errors="replace")

    def _docker(self, *args: str, timeout: int = _DOCKER_TIMEOUT) -> str:
        try:
            result = subprocess.run(["docker", *args], env=self.client_env,
                                    capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise JobError("egress_network_unavailable") from exc
        if result.returncode:
            raise JobError("egress_network_unavailable")
        return result.stdout.strip()

    def _docker_quiet(self, *args: str) -> None:
        try:
            subprocess.run(["docker", *args], env=self.client_env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=_DOCKER_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def pull(self) -> None:
        if not self._pulled:
            self._docker("pull", "--quiet", PROXY_IMAGE, timeout=_PULL_TIMEOUT)
            self._pulled = True

    def start(self) -> "TeamEgress":
        try:
            self.pull()
            self._docker("network", "create", "--internal", "--label", "observer.project-runtime=true", self.network)
            command = ["docker", "run", "--rm", "--interactive", "--name", self.proxy_name,
                       "--label", "observer.project-runtime=true", "--network", self.network,
                       # Public resolvers: a host resolver that answers with placeholder
                       # (non-public) addresses would otherwise refuse every domain.
                       "--dns", "1.1.1.1", "--dns", "8.8.8.8",
                       # Port 443 without any capability: only this namespaced sysctl.
                       "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
                       "--user", "65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                       "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=16m",
                       "--memory", "256m", "--pids-limit", "256", "--cpus", "1",
                       "--log-driver", "none", "--entrypoint", "python3", PROXY_IMAGE, "-u", "-"]
            try:
                self.process = subprocess.Popen(command, env=self.client_env, stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            except OSError:
                raise JobError("egress_proxy_failed") from None
            try:
                self.process.stdin.write(self._script)
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            self._stderr_thread = threading.Thread(target=self._drain, args=(self.process.stderr,), daemon=True)
            self._stderr_thread.start()
            self._await_ready()
            address = self._docker("inspect", "--format",
                                   "{{(index .NetworkSettings.Networks \"" + self.network + "\").IPAddress}}",
                                   self.proxy_name)
            if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", address):
                raise JobError("egress_proxy_failed")
            self.address = address
            # Upstream-facing on the default bridge; the participant never joins it.
            self._docker("network", "connect", "bridge", self.proxy_name)
        except Exception:
            self.close()
            raise
        return self

    def _await_ready(self) -> None:
        deadline = time.monotonic() + 60
        stdout = self.process.stdout if self.process is not None else None
        buffer = b""
        while stdout is not None and time.monotonic() < deadline:
            ready, _, _ = select.select([stdout], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                break
            chunk = os.read(stdout.fileno(), 64)
            if not chunk:
                break
            buffer += chunk
            if b"\n" in buffer:
                if buffer.split(b"\n", 1)[0] == b"READY":
                    return
                break
        raise JobError("egress_proxy_failed")

    def _drain(self, stream) -> None:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            self._log.extend(chunk)
            if len(self._log) > 8192:
                del self._log[:-4096]

    def close(self) -> None:
        self._docker_quiet("rm", "--force", self.proxy_name)
        process, self.process = self.process, None
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    stream.close()
                except (OSError, AttributeError):
                    pass
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2)
            self._stderr_thread = None
        self._docker_quiet("network", "rm", self.network)


assert NETWORK_PATTERN.fullmatch("observer-egress-" + "0" * 32)
