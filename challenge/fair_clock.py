"""Fair clock: a card's time budget counts only the agent's own work, in normalized seconds.

Evaluation machines differ in speed, so a fixed budget of real seconds buys different amounts
of computation. This module charges the budget in *normalized seconds*:

* The machine's speed is measured with a fixed, short, single-thread Python workload
  (``workload``). ``speed_factor = measured time / REFERENCE_UNIT_SECONDS``: 1.0 on the reference
  machine (the median GitHub-hosted evaluation runner), above 1 on a slower machine, below 1 on a
  faster one. It is measured before the run (5 repetitions, agent not started yet) and again about
  every ``SAMPLE_INTERVAL_SECONDS`` between decisions (3 repetitions, the agent frozen meanwhile);
  the factor in use is the median of the last ``WINDOW`` samples.
* Only the agent is charged. A turn runs from sending a ``decision_request`` until the response
  arrives. During a turn, seconds in which the agent's processes were computing (their CPU time,
  at most the turn's length) are divided by the speed factor; the rest of the turn (waiting on a
  model API or the network) counts one to one. Between turns the engine simulates, which is never
  charged; computation the agent keeps doing in the background meanwhile is charged like a turn's.
  Without a CPU meter (for example a local run on Windows) every turn second counts as computing.
* The agent is told the remaining budget in real seconds of *this* machine if spent computing
  (``remaining = (budget - charged) * speed_factor``), so its own timers agree with it. The
  normalized values and the factor are sent alongside.
* A hard wall-clock cap of ``HARD_CAP_MULTIPLIER`` x budget from the first request bounds every
  run, whatever the factor.

The engine itself stays deterministic: timing only decides when the run ends, never how an
action is simulated or scored. Pure standard library.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from typing import Callable

# Median time of one ``workload()`` on GitHub-hosted evaluation runners (ubuntu-24.04, Python
# 3.12), measured 2026-10-04 on 32 runners (2- and 4-vCPU): 0.253 s, range 0.12-0.30 s. The
# reference machine is that median runner. See docs/fair-clock.md.
REFERENCE_UNIT_SECONDS = 0.25
START_REPEATS = 5
SAMPLE_REPEATS = 3
SAMPLE_INTERVAL_SECONDS = 60.0
WINDOW = 5
FACTOR_BOUNDS = (0.1, 10.0)
HARD_CAP_MULTIPLIER = 3.0
CLOCK_SCHEMA = "fair-clock-v1"


def workload() -> float:
    """One calibration unit: a fixed single-thread mix that resembles agent planning code
    (float geometry, dictionary bookkeeping, sorting, lists of rows, JSON). Its result is
    returned only so that no step can be optimized away."""
    n = 280000
    acc = 0.0
    for i in range(n):
        x = i * 1e-4
        acc += math.sin(x) * math.cos(0.5 * x) + math.sqrt(x + 1.0) - math.atan2(x, 1.0 + x)
    table: dict[int, int] = {}
    for i in range(n):
        key = (i * 7919) % 4099
        table[key] = table.get(key, 0) + (i & 7)
    pairs = sorted(((i * 2654435761) % 1000003, i) for i in range(n // 2))
    rows = [[float(i), i * 0.5, -i] for i in range(n // 8)]
    best = max(rows, key=lambda row: row[1] - row[0] * 1e-3)
    json.loads(json.dumps(rows[:2000]))
    return acc + len(table) + pairs[0][0] + best[0]


def time_unit(timer: Callable[[], float] = time.perf_counter) -> float:
    started = timer()
    workload()
    return timer() - started


def _median(values) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else 0.5 * (ordered[middle - 1] + ordered[middle])


class SpeedGauge:
    """Speed factor from repeated calibration samples (median of medians, recent window)."""

    def __init__(self, reference: float = REFERENCE_UNIT_SECONDS, measure: Callable[[], float] = time_unit,
                 window: int = WINDOW) -> None:
        self.reference = float(reference)
        self.measure = measure
        self.window = window
        self.samples: list[float] = []

    def sample(self, repeats: int) -> float:
        self.samples.append(_median([self.measure() for _ in range(max(1, repeats))]))
        return self.factor

    @property
    def factor(self) -> float:
        if not self.samples:
            return 1.0
        low, high = FACTOR_BOUNDS
        return min(high, max(low, _median(self.samples[-self.window:]) / self.reference))


class FairClock:
    """Budget accounting for one run. ``cpu()`` returns the agent's cumulative CPU seconds (or
    None when it cannot be read); ``pause()``/``resume()`` freeze the agent while the speed is
    sampled. All three are optional."""

    def __init__(self, budget: float, *, gauge: SpeedGauge | None = None, clock: Callable[[], float] = time.monotonic,
                 cpu: Callable[[], float | None] | None = None, pause: Callable[[], None] | None = None,
                 resume: Callable[[], None] | None = None, interval: float = SAMPLE_INTERVAL_SECONDS,
                 hard_cap_multiplier: float = HARD_CAP_MULTIPLIER) -> None:
        self.budget = float(budget)
        self.gauge = gauge or SpeedGauge()
        self.clock = clock
        self.cpu, self.pause, self.resume = cpu, pause, resume
        self.interval = interval
        self.hard_cap = hard_cap_multiplier * self.budget
        self.charged = 0.0          # normalized seconds
        self.turn_seconds = 0.0     # real seconds inside turns
        self.busy_seconds = 0.0     # real computing seconds inside turns
        self.background_seconds = 0.0  # real computing seconds between turns
        self.started: float | None = None
        self.next_sample = 0.0
        self.meter = "none"
        self._mark: tuple[float, float | None] | None = None  # (clock, cpu) at the last turn boundary
        self._turn: tuple[float, float | None] | None = None
        self._factors: list[float] = []

    # --- calibration ----------------------------------------------------------------------------

    def calibrate(self) -> float:
        """Before the agent starts: the first speed sample."""
        factor = self.gauge.sample(START_REPEATS)
        self._factors.append(factor)
        return factor

    def _resample(self) -> None:
        paused = False
        try:
            if self.pause is not None:
                self.pause()
                paused = True
            self._factors.append(self.gauge.sample(SAMPLE_REPEATS))
        finally:
            if paused and self.resume is not None:
                self.resume()
        self.next_sample = self.clock() + self.interval

    @property
    def factor(self) -> float:
        return self.gauge.factor

    # --- metering ---------------------------------------------------------------------------------

    def _cpu(self) -> float | None:
        if self.cpu is None:
            return None
        try:
            value = self.cpu()
        except Exception:  # noqa: BLE001 - a meter that fails is treated as unavailable
            value = None
        if value is None:
            self.cpu = None  # gone (for example the agent exited): later turns count as computing
        else:
            self.meter = "cpu"
        return value

    def _busy(self, start: tuple[float, float | None], wall: float, cpu_now: float | None, *, default: float) -> float:
        if cpu_now is None or start[1] is None:
            return default
        return min(wall, max(0.0, cpu_now - start[1]))

    def agent_started(self) -> None:
        """When the agent's processes start (initialize is sent): their CPU counters start at
        zero, so computation before the first request (reading initialize) is charged too."""
        self._mark = (self.clock(), 0.0 if self.cpu is not None else None)

    def begin_turn(self) -> None:
        """Just before a decision_request is sent."""
        now = self.clock()
        if self.started is None:
            self.started = now
            self.next_sample = now + self.interval
        cpu_now = self._cpu()
        if self._mark is not None:
            wall = now - self._mark[0]
            background = self._busy(self._mark, wall, cpu_now, default=0.0)
            self.background_seconds += background
            self.charged += background / self.factor
        if now >= self.next_sample:
            self._resample()
        self._turn = (self.clock(), self._cpu())

    def end_turn(self) -> float:
        """Right after the response (or the end of the turn); returns the charge in normalized s."""
        now = self.clock()
        start = self._turn or (now, None)
        wall = max(0.0, now - start[0])
        cpu_now = self._cpu()
        busy = self._busy(start, wall, cpu_now, default=wall)
        charge = busy / self.factor + (wall - busy)
        self.turn_seconds += wall
        self.busy_seconds += busy
        self.charged += charge
        self._mark = (now, cpu_now)
        self._turn = None
        return charge

    # --- what the agent and the transport see -----------------------------------------------------

    @property
    def remaining(self) -> float:
        """Normalized seconds left."""
        return max(0.0, self.budget - self.charged)

    @property
    def expired(self) -> bool:
        return self.charged >= self.budget or self.wall_left() <= 0.0

    def wall_left(self) -> float:
        if self.started is None:
            return self.hard_cap
        return self.hard_cap - (self.clock() - self.started)

    def turn_deadline(self) -> float:
        """Latest moment (same clock) a response to the current request can still be accepted:
        all remaining budget spent waiting (factor >= 1) or computing (factor < 1)."""
        now = self.clock()
        return now + min(self.remaining * max(1.0, self.factor), max(0.0, self.wall_left()))

    def snapshot(self) -> dict:
        factor = self.factor
        return {
            "elapsed_seconds": round(self.charged * factor, 3),
            "remaining_seconds": round(self.remaining * factor, 3),
            "speed_factor": round(factor, 4),
            "normalized_elapsed_seconds": round(self.charged, 3),
            "normalized_remaining_seconds": round(self.remaining, 3),
        }

    def summary(self) -> dict:
        wall = 0.0 if self.started is None else self.clock() - self.started
        return {
            "schema_version": CLOCK_SCHEMA,
            "budget_seconds": self.budget,
            "charged_seconds": round(min(self.charged, self.budget), 3),
            "speed_factor": round(self.factor, 4),
            "speed_factor_min": round(min(self._factors), 4) if self._factors else None,
            "speed_factor_max": round(max(self._factors), 4) if self._factors else None,
            "speed_samples": len(self._factors),
            "turn_seconds": round(self.turn_seconds, 3),
            "busy_seconds": round(self.busy_seconds, 3),
            "background_seconds": round(self.background_seconds, 3),
            "run_wall_seconds": round(wall, 3),
            "hard_cap_seconds": self.hard_cap,
            "hard_cap_reached": self.started is not None and wall >= self.hard_cap,
            "cpu_meter": self.meter,
        }


# --- agent hooks -----------------------------------------------------------------------------------

def _cgroup_cpu_reader(pid: int) -> Callable[[], float | None] | None:
    """CPU seconds of the cgroup that ``pid`` lives in (cgroup v2 cpu.stat, or v1 cpuacct)."""
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            path = "/sys/fs/cgroup" + parts[2] + "/cpu.stat"

            def read_v2(path=path):
                with open(path, encoding="utf-8") as stat:
                    for row in stat:
                        if row.startswith("usage_usec "):
                            return int(row.split()[1]) / 1e6
                return None
            try:
                if read_v2() is not None:
                    return read_v2
            except OSError:
                pass
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and "cpuacct" in parts[1].split(","):
            path = f"/sys/fs/cgroup/{parts[1]}{parts[2]}/cpuacct.usage"

            def read_v1(path=path):
                with open(path, encoding="utf-8") as usage:
                    return int(usage.read().strip()) / 1e9
            try:
                read_v1()
                return read_v1
            except (OSError, ValueError):
                pass
    return None


class DockerAgent:
    """Hooks for an agent in a Docker container (the platform): freeze with ``docker pause``,
    meter the container's cgroup. The container is found by name on first use."""

    def __init__(self, name: str, environment: dict | None = None) -> None:
        self.name = name
        self.environment = environment
        self._reader: Callable[[], float | None] | None = None
        self._tried = False

    def _docker(self, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], env=self.environment, capture_output=True, text=True,
                              timeout=timeout, check=False)

    def pause(self) -> None:
        self._docker("pause", self.name)

    def resume(self) -> None:
        self._docker("unpause", self.name)

    def cpu(self) -> float | None:
        if self._reader is None and not self._tried:
            deadline = time.monotonic() + 10
            while self._reader is None and time.monotonic() < deadline:
                result = self._docker("inspect", "-f", "{{.State.Pid}}", self.name, timeout=10)
                pid = result.stdout.strip()
                if result.returncode == 0 and pid.isdigit() and int(pid) > 0:
                    self._reader = _cgroup_cpu_reader(int(pid))
                    break
                time.sleep(0.1)
            self._tried = True
        return None if self._reader is None else self._reader()


class ProcessAgent:
    """Hooks for an agent that is a local process group (the local runners): SIGSTOP/SIGCONT,
    CPU time of the process and its children (Linux /proc, macOS libproc)."""

    def __init__(self, process) -> None:
        self.process = process
        self._darwin = _darwin_cpu() if sys.platform == "darwin" else None

    def _signal(self, sig) -> None:
        if self.process is None or self.process.poll() is not None or not hasattr(os, "killpg"):
            return
        try:
            os.killpg(self.process.pid, sig)
        except OSError:
            pass

    def pause(self) -> None:
        if hasattr(signal, "SIGSTOP"):
            self._signal(signal.SIGSTOP)

    def resume(self) -> None:
        if hasattr(signal, "SIGCONT"):
            self._signal(signal.SIGCONT)

    def cpu(self) -> float | None:
        if self.process is None:
            return None
        pid = self.process.pid
        if sys.platform.startswith("linux"):
            return _linux_tree_cpu(pid)
        if self._darwin is not None:
            return self._darwin(pid)
        return None


_TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") and "SC_CLK_TCK" in getattr(os, "sysconf_names", {}) else 100


def _linux_tree_cpu(pid: int) -> float | None:
    total, stack, seen = 0, [pid], set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            with open(f"/proc/{current}/stat", encoding="utf-8") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
        except OSError:
            if current == pid:
                return None
            continue
        total += sum(int(value) for value in fields[11:15])  # utime stime cutime cstime
        try:
            for task in os.listdir(f"/proc/{current}/task"):
                with open(f"/proc/{current}/task/{task}/children", encoding="utf-8") as handle:
                    stack.extend(int(child) for child in handle.read().split())
        except OSError:
            pass
    return total / _TICKS


def _darwin_cpu():
    """proc_pid_rusage(RUSAGE_INFO_V2) user+system time of one process, or None."""
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib")
        libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")

        class Info(ctypes.Structure):  # rusage_info_v2 prefix: uuid, user, system, ...
            _fields_ = [("uuid", ctypes.c_uint8 * 16), ("user", ctypes.c_uint64), ("system", ctypes.c_uint64),
                        ("rest", ctypes.c_uint64 * 30)]

        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

        timebase = Timebase()
        libc.mach_timebase_info(ctypes.byref(timebase))
        scale = timebase.numer / timebase.denom / 1e9 if timebase.denom else 1e-9

        def read(pid: int) -> float | None:
            info = Info()
            if libproc.proc_pid_rusage(int(pid), 2, ctypes.byref(info)) != 0:
                return None
            return (info.user + info.system) * scale
        return read
    except Exception:  # noqa: BLE001 - no meter; every turn second counts as computing
        return None


def container_name(command) -> str | None:
    """The ``--name`` of a ``docker run`` command line, if any."""
    command = list(command or ())
    if command[:2] != ["docker", "run"]:
        return None
    for index, value in enumerate(command[:-1]):
        if value == "--name" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", command[index + 1]):
            return command[index + 1]
    return None
