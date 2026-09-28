#!/usr/bin/env python3
"""Local engine for participant-agent-protocol-v4: a JSON-Lines agent process driving the v4 runner.

TODO(v4 switch): replace this module with a vendored copy of the platform's challenge/v4_workflow.py
(W1 PR-2, gosimfoundation/hackathon-survey26#95) once that PR merges, so local runs use exactly the
platform adapter. Until then this file mirrors it: same initialize/snapshot/finish payloads, same
envelope checks, same validation (v4_runner.normalize_action), same wall-clock rule.

This is the starter kit's stand-in for the platform's colocated v4 engine adapter. It follows the frozen
protocol plus the W1 clarifications (docs: README.md, "Protocol"):

  engine -> agent   initialize        (once, no reply; v4-initialize-v1)
  engine -> agent   decision_request  (v4-decision-snapshot-v1), agent replies with one decision_response
  engine -> agent   finish            (once at the end, no reply; v4-finish-v1), then stdin is closed

The envelope is checked here; the action itself is validated by the runner (v4_runner.normalize_action),
which also expands `wait` + `until_utc` without a round trip. An invalid response ends the run as
`agent_error`; the score is still settled on the valid history. The global wall clock starts at the
first decision_request and covers engine plus agent time. When it expires the survey stops there.
An agent still computing at that moment is stopped at once and gets no `finish` (as on the platform).

Hidden truth (weather, events, faults) stays inside this process; only public fields are sent.
Pure standard library.
"""
from __future__ import annotations

import csv
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping

from .v4_fiber_map import FiberGrid
from .v4_runner import (
    MAX_CONSECUTIVE_ZERO_TIME_ACTIONS,
    TERMINATION_AGENT_ERROR,
    TERMINATION_WALLCLOCK,
    AgentTermination,
    run_scenario,
)

PROTOCOL_VERSION = "participant-agent-protocol-v4"
INITIALIZE_SCHEMA = "v4-initialize-v1"
SNAPSHOT_SCHEMA = "v4-decision-snapshot-v1"
FINISH_SCHEMA = "v4-finish-v1"
WORKFLOW_RESULT_SCHEMA = "v4-local-workflow-result-v1"
MAX_RESPONSE_BYTES = 512 * 1024
FINISH_GRACE_SECONDS = 30.0
PLATFORM_WALLCLOCK_CAP = 900.0
ENVELOPE_KEYS = ("protocol_version", "message_type", "decision_sequence", "reason", "decision_source")
FIBER_LAYOUT = ("row-major, fiber 0 bottom-left; rows along +alt, columns along +az at exposure start; "
                "gnomonic plane centred on the actual pointing")


class GlobalDeadlineExpired(TimeoutError):
    """The global wall clock ran out while talking to the agent."""


class AgentProtocolError(ValueError):
    """The agent sent something the protocol does not allow."""


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# --- initialize ----------------------------------------------------------------------------------


def scenario_path(card_dir: Path) -> Path:
    return Path(card_dir) / "config" / "v4_scenario.json"


def load_card(card_dir: Path) -> dict:
    """Public card metadata from config/v4_scenario.json (task_card, site, limits)."""
    config = json.loads(scenario_path(card_dir).read_text(encoding="utf-8"))
    task_card = config.get("task_card") or {"card_id": config["name"], "scenario_slug": config["name"], "phase": "local"}
    return {**task_card, "site_name": config["site"]["name"],
            "wallclock_limit": float((config.get("limits") or {}).get("global_wallclock_seconds", PLATFORM_WALLCLOCK_CAP))}


def effective_wallclock(card_dir: Path, requested: float) -> float:
    """Same rule as the platform: min(requested, the card's limit, 900 s)."""
    return min(float(requested), load_card(card_dir)["wallclock_limit"], PLATFORM_WALLCLOCK_CAP)


def build_initialize(card_dir: Path, wallclock_seconds: float) -> dict:
    """The public `initialize` payload. Never contains weather truth, events, faults or seeds."""
    path = scenario_path(card_dir)
    config = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    fiber = json.loads((base / config["fiber_config"]).read_text(encoding="utf-8"))
    score = json.loads((base / config["score_config"]).read_text(encoding="utf-8"))
    products = config["products"]
    grid = FiberGrid.from_config(fiber)
    slots = _read_csv((base / products["slots_csv"]).resolve())
    nights = _read_csv((base / products["night_calendar_csv"]).resolve())
    start = _parse_utc(slots[0]["timestamp_utc"])
    end = _parse_utc(slots[-1]["timestamp_utc"]) + timedelta(seconds=int(slots[-1]["duration_seconds"]))
    footprint: dict[str, list[list[float]]] = {}
    for row in _read_csv((base / products["footprint_csv"]).resolve()):
        footprint.setdefault(row["component_id"], []).append([float(row["ra_deg"]), float(row["dec_deg"])])
    columns = ["target_id", "ra_deg", "dec_deg", "target_class", "feature_flux", "science_weight", "required"]
    rows = [[row["target_id"], float(row["ra_deg"]), float(row["dec_deg"]), row["target_class"],
             float(row["feature_flux"]), float(row["science_weight"]), row["required"].strip().lower() == "true"]
            for row in _read_csv((base / products["targets_csv"]).resolve())]
    site = config["site"]
    card = load_card(card_dir)
    return {
        "schema_version": INITIALIZE_SCHEMA,
        "task_card": {"card_id": card["card_id"], "scenario_slug": card["scenario_slug"], "phase": card["phase"]},
        "site": {
            "name": site["name"],
            "latitude_deg": float(site["latitude_deg"]),
            "longitude_deg": float(site["longitude_deg"]),
            "utc_offset_hours": float(site["utc_offset_hours"]),
            "sun_altitude_limit_deg": float(site.get("sun_altitude_limit_deg", -18.0)),
            "minimum_altitude_deg": float(config["minimum_altitude_deg"]),
        },
        "survey": {
            "start_utc": _format_utc(start),
            "end_utc": _format_utc(end),
            "slot_seconds": int(slots[0]["duration_seconds"]),
            "nights": [{"night_id": row["night_id"], "night_date": row["night_date"],
                        "observing_start_utc": row["observing_start_utc"], "observing_end_utc": row["observing_end_utc"],
                        "slot_count": int(row["slot_count"])} for row in nights],
        },
        "instrument": {
            "n_fibers": grid.n_fibers,
            "grid_side": grid.n_side,
            "fiber_area_deg2": grid.fiber_area_deg2,
            "gap_deg": grid.gap_deg,
            "glass_side_deg": round(grid.fiber_side_deg, 6),
            "pitch_deg": round(grid.pitch_deg, 6),
            "fov_side_deg": round(grid.fov_side_deg, 6),
            "layout": FIBER_LAYOUT,
            "exposure": {"min_duration_seconds": int(fiber["exposure"]["min_duration_seconds"]),
                         "max_duration_seconds": int(fiber["exposure"]["max_duration_seconds"])},
        },
        "scoring": score,
        "footprint": [{"component_id": key, "vertices": value} for key, value in footprint.items()],
        "targets": {"columns": columns, "rows": rows},
        "limits": {
            "global_wallclock_seconds": float(wallclock_seconds),
            "max_consecutive_zero_time_actions": MAX_CONSECUTIVE_ZERO_TIME_ACTIONS,
            "response_max_bytes": MAX_RESPONSE_BYTES,
            "decision_timeout": "global only (no per-decision timeout)",
        },
    }


# --- response envelope ---------------------------------------------------------------------------


def check_envelope(response: Mapping, sequence: int) -> dict:
    """Check the decision_response envelope and return the bare action for the runner.

    The runner (v4_runner.normalize_action) then validates the action fields exactly: unknown keys,
    out-of-range values, unknown targets and repeated fibres all end the run as agent_error."""
    if not isinstance(response, Mapping):
        raise AgentProtocolError("response must be a JSON object")
    if response.get("protocol_version") != PROTOCOL_VERSION:
        raise AgentProtocolError(f"protocol_version must be {PROTOCOL_VERSION}")
    if response.get("message_type") != "decision_response":
        raise AgentProtocolError("message_type must be decision_response")
    if type(response.get("decision_sequence")) is not int or response["decision_sequence"] != sequence:
        raise AgentProtocolError(f"decision_sequence must be {sequence} (the request's number)")
    for key in ("reason", "decision_source"):
        if key in response and not isinstance(response[key], str):
            raise AgentProtocolError(f"{key} must be a string")
    return {key: value for key, value in response.items() if key not in ENVELOPE_KEYS}


# --- agent process -------------------------------------------------------------------------------


class AgentProcess:
    """A persistent JSON-Lines subprocess. Reads and writes run on helper threads so the global
    deadline holds on every platform (including Windows) even for multi-megabyte messages."""

    def __init__(self, command: list[str], *, cwd: Path, env: Mapping[str, str], stderr=None,
                 initialization_seconds: float = 30.0):
        self.command = list(command)
        self.cwd = Path(cwd)
        self.env = dict(env)
        self.stderr = stderr
        self.initialization_seconds = initialization_seconds
        self.process: subprocess.Popen | None = None
        self._lines: "queue.Queue[bytes | Exception | None]" = queue.Queue()

    def start(self) -> None:
        if self.process is not None:
            return
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                 else {"start_new_session": True})
        self.process = subprocess.Popen(self.command, cwd=str(self.cwd), env=self.env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.stderr, bufsize=0, **group)
        threading.Thread(target=self._pump, args=(self.process.stdout,), daemon=True).start()

    def _pump(self, stream) -> None:
        buffer = bytearray()
        while True:
            try:
                chunk = stream.read(65536) if hasattr(stream, "read") else b""
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                self._lines.put(None)
                return
            buffer.extend(chunk)
            while b"\n" in buffer:
                line, _, rest = bytes(buffer).partition(b"\n")
                buffer = bytearray(rest)
                self._lines.put(line)
            if len(buffer) > MAX_RESPONSE_BYTES:
                self._lines.put(AgentProtocolError(f"response line exceeds {MAX_RESPONSE_BYTES} bytes"))
                return

    def send(self, message: Mapping, deadline: float) -> None:
        self.start()
        data = (json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        failure: list[BaseException] = []

        def write() -> None:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except BaseException as exc:  # noqa: BLE001 - a closed pipe when the agent exits
                failure.append(exc)

        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        writer.join(max(0.0, deadline - time.monotonic()))
        if writer.is_alive():
            self.close(force=True)
            raise GlobalDeadlineExpired()
        if failure:
            raise AgentProtocolError(f"agent exited before reading the next message (exit code {self.process.poll()})")

    def receive(self, deadline: float) -> dict:
        try:
            item = self._lines.get(timeout=max(0.0, deadline - time.monotonic()))
        except queue.Empty:
            self.close(force=True)  # still computing at the deadline: stopped at once, no finish message
            raise GlobalDeadlineExpired() from None
        if item is None:
            raise AgentProtocolError(f"agent exited without a response (exit code {self.process.poll() if self.process else None})")
        if isinstance(item, Exception):
            raise item
        if len(item) > MAX_RESPONSE_BYTES:
            raise AgentProtocolError(f"response line exceeds {MAX_RESPONSE_BYTES} bytes")
        try:
            payload = json.loads(item.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError) as exc:
            raise AgentProtocolError("stdout must carry one JSON object per line; print logs to stderr") from exc
        if not isinstance(payload, dict):
            raise AgentProtocolError("response must be a JSON object")
        return payload

    def publish_initial(self, payload: Mapping) -> None:
        self.send({"protocol_version": PROTOCOL_VERSION, "message_type": "initialize", "payload": payload},
                  time.monotonic() + self.initialization_seconds)

    def request(self, sequence: int, payload: Mapping, deadline: float) -> dict:
        self.send({"protocol_version": PROTOCOL_VERSION, "message_type": "decision_request",
                   "decision_sequence": sequence, "payload": payload}, deadline)
        return self.receive(deadline)

    def finish(self, payload: Mapping, grace_seconds: float = FINISH_GRACE_SECONDS) -> None:
        """One final `finish` line, stdin EOF, then up to grace_seconds to exit. Never raises."""
        process = self.process
        if process is None:
            return
        grace_deadline = time.monotonic() + grace_seconds
        if process.poll() is None:
            try:
                self.send({"protocol_version": PROTOCOL_VERSION, "message_type": "finish", "payload": dict(payload)},
                          grace_deadline)
            except Exception:  # noqa: BLE001
                pass
        if self.process is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=max(0.0, grace_deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        self.close()

    def close(self, force: bool = False) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=10)
                else:
                    import signal  # noqa: PLC0415
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL if force else signal.SIGTERM)
            except Exception:  # noqa: BLE001
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass
        self.process = None


# --- run -----------------------------------------------------------------------------------------


def run_card(card_dir: Path, agent: AgentProcess, output_dir: Path, *, wallclock_seconds: float,
             clock: Callable[[], float] = time.monotonic, grace_seconds: float = FINISH_GRACE_SECONDS) -> dict:
    """Run one card against one agent process. Returns the workflow result (with the score report)."""
    card_dir = Path(card_dir)
    output_dir = Path(output_dir)
    card = load_card(card_dir)
    budget = effective_wallclock(card_dir, wallclock_seconds)
    state: dict = {"sequence": 0, "accepted": 0, "deadline": None, "started": None, "transport_error": None}

    def decide(snapshot: Mapping):
        if state["deadline"] is None:
            state["started"] = clock()
            state["deadline"] = state["started"] + budget
        if clock() >= state["deadline"]:
            raise AgentTermination(TERMINATION_WALLCLOCK, "wall clock expired between decisions")
        state["sequence"] += 1
        sequence = state["sequence"]
        elapsed = clock() - state["started"]
        payload = {
            "schema_version": SNAPSHOT_SCHEMA,
            "now_utc": snapshot["now_utc"],
            "survey_end_utc": snapshot["survey_end_utc"],
            "observe_action_index": snapshot["observe_action_index"],
            "running_total": snapshot["running_total"],
            "wallclock": {"elapsed_seconds": round(elapsed, 3), "remaining_seconds": round(max(0.0, budget - elapsed), 3)},
            "latest_bulletin": snapshot["latest_bulletin"],
            "latest_forecast": snapshot["latest_forecast"],
            "new_messages": snapshot["new_messages"],
            "last_result": snapshot["last_result"],
        }
        try:
            response = agent.request(sequence, payload, state["deadline"])
        except GlobalDeadlineExpired:
            raise AgentTermination(TERMINATION_WALLCLOCK, f"decision {sequence}: no answer before the deadline") from None
        except Exception as exc:  # noqa: BLE001
            state["transport_error"] = True
            raise AgentTermination(TERMINATION_AGENT_ERROR, f"decision {sequence}: {exc}") from None
        if clock() >= state["deadline"]:
            raise AgentTermination(TERMINATION_WALLCLOCK, f"decision {sequence}: answer arrived after the deadline")
        try:
            action = check_envelope(response, sequence)
        except AgentProtocolError as exc:
            state["transport_error"] = True
            raise AgentTermination(TERMINATION_AGENT_ERROR, f"decision {sequence}: {exc}") from None
        state["accepted"] = sequence
        return action

    def factory(_context: Mapping):
        try:
            agent.publish_initial(build_initialize(card_dir, budget))
        except Exception as exc:  # noqa: BLE001
            state["transport_error"] = True
            raise AgentTermination(TERMINATION_AGENT_ERROR, f"initialize: {exc}") from None
        return decide

    report = run_scenario(scenario_path(card_dir), factory, output_dir)
    report.pop("organizer_only", None)  # hidden stress truth never leaves the engine
    termination = report["termination"]["reason"]
    detail = report["termination"]["detail"]
    if termination == TERMINATION_AGENT_ERROR and not state["transport_error"]:
        detail = f"decision {state['accepted']}: {detail}"  # the runner rejected the action itself
        state["accepted"] -= 1
    accounted = 0.0 if state["started"] is None else min(clock(), state["deadline"]) - state["started"]
    agent.finish({"schema_version": FINISH_SCHEMA, "termination_reason": termination,
                  "decisions": int(report["counts"]["decisions"]), "observe_actions": int(report["counts"]["observe_actions"]),
                  "last_decision_sequence": max(0, state["accepted"]), "grace_seconds": grace_seconds},
                 grace_seconds=grace_seconds)
    result = {
        "schema_version": WORKFLOW_RESULT_SCHEMA,
        "protocol_version": PROTOCOL_VERSION,
        "card_id": card["card_id"],
        "termination_reason": termination,
        "error": detail if termination == TERMINATION_AGENT_ERROR else None,
        "termination_detail": detail,
        "global_wallclock_seconds": budget,
        "accounted_wallclock_seconds": round(max(0.0, accounted), 3),
        "decision_requests": state["sequence"],
        "score": {"total": report["total"], **report["components"]},
        "counts": report["counts"],
    }
    (output_dir / "workflow_result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**result, "score_report": report}
