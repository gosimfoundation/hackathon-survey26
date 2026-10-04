"""Team egress: what the participant container can reach during a run.

The participant container joins a per-run internal Docker network (no route
anywhere). Its only neighbour is a small forwarder sidecar: trusted engine code
on a pinned image, dual-homed onto the default bridge. The sidecar accepts

* HTTPS CONNECT on port 3128 (``HTTPS_PROXY``; standard SDKs use it),
* direct TLS on port 443, spliced by the ClientHello's server name, and
* (open mode) plain HTTP on port 80, spliced by its ``Host`` header,

for clients that ignore proxy settings. Two modes:

* **open** (default for teams on open egress): any public destination on port
  443 or 80. The sidecar is also the container's DNS server and answers every
  name with its own address, so every connection by name reaches it.
* **allow-list**: only the team's listed domains on port 443, mapped to the
  sidecar in the participant's ``/etc/hosts`` (the earlier behaviour; rollback).

In both modes the sidecar resolves the destination itself, refuses it unless
every address is public (no private, loopback, link-local, CGNAT, multicast,
benchmarking or metadata range, also for IPv4-mapped IPv6), and connects only to
those checked addresses, so a name that resolves (or rebinds) to an internal
address never reaches an internal service. TLS stays end to end; the sidecar
never sees plaintext or credentials. It records, per destination host and port,
the number of connections (and refusals), bytes each way and the first/last
time (``report``); never any payload. The team's variables (API keys, base URLs,
model names) are injected into the participant container as environment
variables; they never reach the sidecar.
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
    if (not isinstance(value, dict) or not {"environment", "secrets", "domains"} <= set(value) <=
            {"environment", "secrets", "domains", "open"} or value.get("open", True) is not True):
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
    return {"environment": dict(environment), "secrets": list(secret_names), "domains": list(domains),
            "open": value.get("open") is True}


# The forwarder inside the sidecar (standard library only). ALLOWED is baked in by
# the trusted engine; unit tests run this exact script in a local process.
PROXY_SCRIPT = r"""
import ipaddress, json, os, re, socket, sys, threading, time
ALLOWED = %(allowed)s            # list of domains, or None: any public destination
PORTS = frozenset(%(ports)s)     # destination ports
DNS = %(dns)d                    # answer every name with this sidecar's address
REPORT = %(report)s              # where the per-destination record is written
# Tests only: {host: [addresses]} instead of DNS, loopback allowed, and every
# connection goes to TEST_PORT. Always empty/0 in production.
TEST_HOSTS, TEST_PORT = %(test_hosts)s, %(test_port)d
CONNECT_PORT, TLS_PORT, HTTP_PORT, DNS_PORT = %(connect_port)d, %(tls_port)d, %(http_port)d, %(dns_port)d
IDLE, CONNECT_TIMEOUT, MAX_CONNECTIONS, MAX_DESTINATIONS = 300, 15, 128, 500
HOST = re.compile(r"^[a-z0-9.:_\[\]-]{1,253}$")
slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
stats, stats_lock, dirty = {}, threading.Lock(), threading.Event()

def now():
    return time.strftime("%%Y-%%m-%%dT%%H:%%M:%%SZ", time.gmtime())

def note(host, port, *, refused=False, up=0, down=0, opened=False):
    host = host if HOST.fullmatch(host or "") else "(invalid)"
    with stats_lock:
        key = (host, port)
        if key not in stats and len(stats) >= MAX_DESTINATIONS:
            key = ("(other)", 0)
        entry = stats.setdefault(key, {"host": key[0], "port": key[1], "connections": 0, "refused": 0,
                                       "bytes_up": 0, "bytes_down": 0, "first": now(), "last": now()})
        entry["connections"] += 1 if opened else 0
        entry["refused"] += 1 if refused else 0
        entry["bytes_up"] += up
        entry["bytes_down"] += down
        entry["last"] = now()
    dirty.set()

def writer():
    while True:
        dirty.wait()
        time.sleep(0.2)
        dirty.clear()
        with stats_lock:
            data = json.dumps(sorted(stats.values(), key=lambda e: (e["host"], e["port"])))
        try:
            with open(REPORT + ".tmp", "w") as handle:
                handle.write(data)
            os.replace(REPORT + ".tmp", REPORT)
        except OSError:
            pass

def public(address):
    ip = ipaddress.ip_address(address.split("%%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if TEST_PORT and ip.is_loopback:
        return True
    return ip.is_global and not ip.is_multicast

def literal(host):
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        return None

def resolve(host, port):
    if TEST_PORT:
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 (a, TEST_PORT)) for a in TEST_HOSTS.get(host, [])]
    address = literal(host)
    if address is not None:
        if ALLOWED is not None:
            return []
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))]
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return [info for info in infos if info[0] in (socket.AF_INET, socket.AF_INET6)]

def upstream(host, port):
    # Resolve here and connect only to the addresses just checked: a name that
    # resolves (or later rebinds) to a private address is refused outright.
    if port not in PORTS or not HOST.fullmatch(host) or (ALLOWED is not None and host not in ALLOWED):
        raise PermissionError(host)
    addresses = resolve(host, port)
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

def pipe(source, target, counter):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            target.sendall(data)
            counter[0] += len(data)
    except OSError:
        pass
    finally:
        for sock, how in ((target, socket.SHUT_WR), (source, socket.SHUT_RD)):
            try:
                sock.shutdown(how)
            except OSError:
                pass

def splice(client, remote, host, port, first=b""):
    up, down = [len(first)], [0]
    try:
        if first:
            remote.sendall(first)
        other = threading.Thread(target=pipe, args=(remote, client, down), daemon=True)
        other.start()
        pipe(client, remote, up)
        other.join(IDLE)
    finally:
        note(host, port, up=up[0], down=down[0])

def open_upstream(host, port):
    try:
        remote = upstream(host, port)
    except OSError:
        # Refused (not public, not allowed, other port) or unreachable: never opened.
        note(host, port, refused=True)
        raise
    note(host, port, opened=True)
    return remote

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
    host = server_name(hello)
    remote = open_upstream(host, 443)
    try:
        splice(client, remote, host, 443, hello)
    finally:
        remote.close()

def read_head(client):
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = client.recv(4096)
        if not chunk or len(head) + len(chunk) > 16384:
            raise ValueError("bad request")
        head += chunk
    return head

def handle_http(client):
    head = read_head(client)
    match = re.search(rb"\r\nhost:[ \t]*([^\r\n]+)", head, re.I)
    if not match:
        raise ValueError("no host")
    host = match.group(1).decode("latin-1").strip().lower().rstrip(".")
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        remote = open_upstream(host, 80)
    except PermissionError:
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    try:
        splice(client, remote, host, 80, head)
    finally:
        remote.close()

def handle_connect(client):
    head = read_head(client)
    line = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
    if len(line) != 3 or line[0] != "CONNECT" or not line[2].startswith("HTTP/1."):
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    host, _, port = line[1].rpartition(":")
    host = host.lower().rstrip(".")
    try:
        remote = open_upstream(host, int(port) if port.isdigit() else -1)
    except PermissionError:
        client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    except OSError:
        client.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
    try:
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        splice(client, remote, host, int(port), head.split(b"\r\n\r\n", 1)[1])
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

def serve_dns(address):
    # Every A question is answered with this sidecar's own address (TTL 5 s);
    # other types get an empty answer. The real resolution happens per connection.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", DNS_PORT))
    own = socket.inet_aton(address)
    while True:
        try:
            data, peer = sock.recvfrom(512)
            if len(data) < 17 or data[2] & 0x80 or int.from_bytes(data[4:6], "big") != 1:
                continue
            pos = 12
            while data[pos]:
                pos += 1 + data[pos]
                if pos >= len(data) - 4:
                    raise ValueError()
            qtype, end = int.from_bytes(data[pos + 1:pos + 3], "big"), pos + 5
            answer = b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x05\x00\x04" + own if qtype == 1 else b""
            flags = b"\x81\x80" if data[2] & 0x01 else b"\x80\x80"
            sock.sendto(data[:2] + flags + b"\x00\x01" + (b"\x00\x01" if answer else b"\x00\x00") +
                        b"\x00\x00\x00\x00" + data[12:end] + answer, peer)
        except Exception:
            continue

threading.Thread(target=writer, daemon=True).start()
threading.Thread(target=serve, args=(TLS_PORT, handle_tls), daemon=True).start()
threading.Thread(target=serve, args=(CONNECT_PORT, handle_connect), daemon=True).start()
if 80 in PORTS:
    threading.Thread(target=serve, args=(HTTP_PORT, handle_http), daemon=True).start()
if DNS:
    threading.Thread(target=serve_dns, args=(socket.gethostbyname(socket.gethostname()),), daemon=True).start()
print("READY", flush=True)
threading.Event().wait()
"""

OPEN_PORTS = (443, 80)
REPORT_PATH = "/tmp/egress.json"


def render_team_proxy_script(domains: list[str] | None, *, connect_port: int = CONNECT_PORT,
                             tls_port: int = TLS_PORT, http_port: int = 80, dns_port: int = 53,
                             report: str = REPORT_PATH, test_hosts: dict[str, list[str]] | None = None,
                             test_port: int = 0, dns: bool | None = None) -> bytes:
    """The sidecar's exact source. ``domains=None`` is open mode (any public destination on
    port 443 or 80, sidecar DNS); a list is the allow-list mode (port 443 only).
    ``test_hosts``/``test_port`` are for tests only: names resolve from that map (loopback
    allowed) and connections go to ``test_port``."""
    if domains is not None and not all(valid_domain(d) or (test_port and d.endswith(".test")) for d in domains):
        raise JobError("invalid_team_egress")
    open_mode = domains is None
    return (PROXY_SCRIPT % {
        "allowed": "None" if open_mode else json.dumps(sorted(domains)),
        "ports": json.dumps(list(OPEN_PORTS) if open_mode else [443]),
        "dns": int(open_mode if dns is None else dns), "report": json.dumps(report),
        "test_hosts": json.dumps(test_hosts or {}), "test_port": test_port, "connect_port": connect_port,
        "tls_port": tls_port, "http_port": http_port, "dns_port": dns_port}).encode()


def checked_report(value: object) -> list[dict]:
    """The sidecar's record, re-validated on the trusted side (it is still trusted code,
    but the participant chose every host name in it)."""
    if not isinstance(value, list):
        return []
    rows = []
    for entry in value[:501]:
        if not isinstance(entry, dict):
            continue
        host, port = entry.get("host"), entry.get("port")
        numbers = [entry.get(k) for k in ("connections", "refused", "bytes_up", "bytes_down")]
        if (not isinstance(host, str) or not re.fullmatch(r"[a-z0-9.:_\[\]()-]{1,253}", host) or
                not isinstance(port, int) or not 0 <= port <= 65535 or
                not all(isinstance(n, int) and 0 <= n < 2 ** 53 for n in numbers) or
                not all(isinstance(entry.get(k), str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ",
                                                                       entry[k]) for k in ("first", "last"))):
            continue
        rows.append({"host": host, "port": port, "connections": numbers[0], "refused": numbers[1],
                     "bytes_up": numbers[2], "bytes_down": numbers[3], "first": entry["first"],
                     "last": entry["last"]})
    return rows


def report_text(rows: list[dict]) -> str:
    """The team-facing summary appended to its own run log."""
    if not rows:
        return "\n--- Network connections during this run (platform record) ---\nnone\n"
    lines = ["", "--- Network connections during this run (platform record; no content is recorded) ---",
             "destination | connections | refused | sent bytes | received bytes | first | last (UTC)"]
    for row in sorted(rows, key=lambda r: (-(r["bytes_up"] + r["bytes_down"]), r["host"], r["port"])):
        lines.append(f"{row['host']}:{row['port']} | {row['connections']} | {row['refused']} | {row['bytes_up']} | "
                     f"{row['bytes_down']} | {row['first']} | {row['last']}")
    return "\n".join(lines) + "\n"


class TeamEgress:
    """Per-run internal network plus the pinned forwarder (open or allow-list mode)."""

    def __init__(self, domains: list[str], *, client_env: dict[str, str], open: bool = False):
        self.open = open
        self.domains = [] if open else list(domains)
        self.report: list[dict] = []
        self.client_env = dict(client_env)
        suffix = uuid.uuid4().hex
        self.network = "observer-egress-" + suffix
        self.proxy_name = "observer-proxy-" + suffix
        self.address: str | None = None
        self.process: subprocess.Popen | None = None
        self._pulled = False
        self._log = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._script = render_team_proxy_script(None if open else self.domains)

    @property
    def environment(self) -> dict[str, str]:
        """Proxy settings for the participant container (lower- and upper-case spellings)."""
        proxy = f"http://{self.address}:{CONNECT_PORT}"
        if self.open:
            # Plain http:// needs no proxy: the sidecar's DNS sends it to port 80, spliced by Host.
            return {"HTTPS_PROXY": proxy, "https_proxy": proxy, "NO_PROXY": "", "no_proxy": "",
                    "NODE_USE_ENV_PROXY": "1"}
        return {"HTTPS_PROXY": proxy, "https_proxy": proxy, "HTTP_PROXY": proxy, "http_proxy": proxy,
                "NO_PROXY": "", "no_proxy": "", "NODE_USE_ENV_PROXY": "1"}

    @property
    def hosts(self) -> list[str]:
        """``--add-host`` values (allow-list mode): every allowed domain points at the sidecar."""
        return [f"{domain}:{self.address}" for domain in self.domains]

    @property
    def dns(self) -> str | None:
        """The participant's DNS server (open mode): the sidecar answers every name with itself."""
        return self.address if self.open else None

    def collect(self) -> list[dict]:
        """The sidecar's per-destination record (best effort; empty if it cannot be read)."""
        if self.process is None:
            return self.report
        time.sleep(1)  # the sidecar writes its record within 0.2 s of the last change
        try:
            result = subprocess.run(["docker", "exec", self.proxy_name, "cat", REPORT_PATH], env=self.client_env,
                                    capture_output=True, text=True, timeout=_DOCKER_TIMEOUT)
            if result.returncode == 0 and len(result.stdout) < 2_000_000:
                self.report = checked_report(json.loads(result.stdout))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
        return self.report

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
        self.collect()
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
