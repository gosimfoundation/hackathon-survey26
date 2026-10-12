"""Console driver: runs the official v4 runner inside Pyodide for the AOH web console.

Loaded by worker.js (browser) and node_golden.mjs (Node); both call ``run_card``.

Modes:
  replay   -- actions come from a recorded list (golden test); no UI round trip.
  human    -- every decision is exchanged with the main thread through a blocking
              JS callback (Atomics.wait on a SharedArrayBuffer; see worker.js).
  assisted -- same transport as human; the UI may prefill suggestions (Task 3).

Human/assisted protocol (multi-round per decision): the agent posts
{"type":"snapshot","seq":n,"snapshot":{...},"view":{...}} and blocks; the UI replies
with {"type":"query",...} (answered with {"type":"answer",...}, loop continues) or
{"type":"action","action":{...},"source":"human"|"assistant"}. Invalid actions are
validated with the runner's own ``normalize_action`` BEFORE reaching the runner; a
validation failure is answered with {"type":"answer","error":...} and the run waits,
so a human typo never ends the run as agent_error.

Key order note: JS objects reorder integer-like keys (fibre ids). Replay actions are
passed to Python as raw JSON text (never parsed in JS); human/assisted actions are
canonicalised to ascending fibre order here so a downloaded log replays identically.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_APP_PY = os.environ.get("AOH_APP_ROOT", "/app") + "/py"
if _APP_PY not in sys.path:
    sys.path.insert(0, _APP_PY)

from challenge.v4_fiber_map import (
    FiberGrid,
    altaz_to_radec,
    altitude_ok,
    radec_to_altaz,
)
from challenge.v4_runner import (
    InvalidAgentAction,
    load_scenario,
    normalize_action,
    run_scenario,
)
from challenge.v4_workflow import V4Workflow

_APP_ROOT = os.environ.get("AOH_APP_ROOT", "/app")
_OUT_ROOT = os.environ.get("AOH_OUT_ROOT", "/out")
CARD_ROOT = _APP_ROOT + "/cards/{card}"
SCENARIO_PATH = CARD_ROOT + "/config/v4_scenario.json"
NIGHT_CSV = CARD_ROOT + "/public/v4_night_calendar.csv"
OUTPUT_DIR = _OUT_ROOT + "/{card}"
_RUNS = 0
SOURCES = {"human", "assistant", "human_accept"}


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _format_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unit(alt_deg: float, az_deg: float) -> tuple[float, float, float]:
    alt, az = math.radians(alt_deg), math.radians(az_deg)
    return (math.cos(alt) * math.cos(az), math.cos(alt) * math.sin(az), math.sin(alt))


def _sun_altaz(moment: datetime, lat: float, lon: float) -> tuple[float, float]:
    """Low-precision solar position (standard astronomical approximation)."""
    days = (moment - datetime(2000, 1, 1, 12, tzinfo=timezone.utc)).total_seconds() / 86400.0
    mean_long = (280.460 + 0.9856474 * days) % 360.0
    mean_anom = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecl_long = math.radians(mean_long + 1.915 * math.sin(mean_anom) + 0.020 * math.sin(2 * mean_anom))
    obliquity = math.radians(23.439 - 0.0000004 * days)
    ra = math.degrees(math.atan2(math.cos(obliquity) * math.sin(ecl_long), math.cos(ecl_long))) % 360.0
    dec = math.degrees(math.asin(math.sin(obliquity) * math.sin(ecl_long)))
    return radec_to_altaz(ra, dec, moment, lat, lon)


def _jsonable(action: dict) -> dict:
    """Canonical JSON-safe copy: datetimes -> '...Z', fibre keys ascending ints."""
    out = dict(action)
    if "until_utc" in out and isinstance(out["until_utc"], datetime):
        out["until_utc"] = _format_utc(out["until_utc"])
    if isinstance(out.get("assignments"), dict):
        out["assignments"] = dict(sorted(out["assignments"].items()))
    return out


def _track_result(env: "_BridgeEnv", snapshot: dict) -> None:
    """Update env's observed-counts / report streak from snapshot.last_result."""
    result = snapshot.get("last_result") or {}
    if result.get("action") == "observe":
        env.observes += 1
        env.consecutive_reports = 0
        for hit in result.get("hits", []):
            tid = hit["target_id"]
            env.observed[tid] = env.observed.get(tid, 0) + 1
    elif result.get("action") == "report":
        env.consecutive_reports += 1
    elif result.get("action") == "wait":
        env.consecutive_reports = 0


def _replay_factory(actions: list[dict], log: list, observer=None, card: str = ""):
    queue = list(actions)

    def factory(context):
        env = _BridgeEnv(card, context) if observer is not None else None

        def agent(snapshot):
            if env is not None:  # replay.html animation stream (non-blocking, mode=replay)
                env.seq += 1
                _track_result(env, snapshot)
                now = _parse_utc(snapshot["now_utc"])
                observer(json.dumps({"type": "snapshot", "seq": env.seq, "snapshot": snapshot,
                                     "view": env.view(snapshot, now)}, default=str))
            if not queue:
                return None
            action = queue.pop(0)  # replayed exactly as recorded (order preserved)
            log.append(action)
            return action

        return agent

    return factory


class _BridgeEnv:
    """Per-run state for the human/assisted agent: view building, queries, validation."""

    def __init__(self, card: str, context: dict) -> None:
        self.lat = float(context["site"]["latitude_deg"])
        self.lon = float(context["site"]["longitude_deg"])
        self.utc_offset = float(context["site"].get("utc_offset_hours", 0.0))
        self.sun_limit = float(context["site"].get("sun_altitude_limit_deg", -18.0))
        self.min_alt = float(context["scenario"]["minimum_altitude_deg"])
        self.grid = FiberGrid.from_config({"field": context["fiber"]})
        self.cfg = {"site": context["site"]}
        self.targets = list(context["targets"])
        self.targets_by_id = {t["target_id"]: t for t in self.targets}
        self.vectors = {
            t["target_id"]: _unit(t["ra_deg"], t["dec_deg"]) for t in self.targets
        }
        fov_radius = math.degrees(
            math.atan(math.sqrt(2.0) * math.radians(self.grid.fov_side_deg / 2.0))
        ) + 0.3
        self.cos_fov = math.cos(math.radians(fov_radius))
        night_csv = Path(NIGHT_CSV.format(card=card))
        with night_csv.open("r", encoding="utf-8", newline="") as handle:
            self.nights = list(csv.DictReader(handle))
        self.scenario = load_scenario(Path(SCENARIO_PATH.format(card=card)))
        self.max_reports = int(
            context.get("score", {}).get("reporting", {}).get("max_consecutive_reports", 32)
        )
        self.observed: dict[str, int] = {}
        self.observes = 0
        self.seq = 0
        self.consecutive_reports = 0

    def view(self, snapshot: dict, now: datetime) -> dict:
        """Cheap public view shipped with every snapshot (see SPEC Task 2 item 3)."""
        sun_alt, _ = _sun_altaz(now, self.lat, self.lon)
        rows = []
        for t in self.targets:
            alt, az = radec_to_altaz(t["ra_deg"], t["dec_deg"], now, self.lat, self.lon)
            if alt >= self.min_alt:
                rows.append([
                    t["target_id"], round(alt, 2), round(az, 2), t["target_class"],
                    t["science_weight"], 1 if t["required"] else 0,
                    self.observed.get(t["target_id"], 0),
                ])
        night = None
        next_start = None
        for i, n in enumerate(self.nights):
            start, end = _parse_utc(n["observing_start_utc"]), _parse_utc(n["observing_end_utc"])
            if start <= now < end:
                night = {"index": i + 1, "count": len(self.nights),
                         "night_id": n["night_id"], "end_utc": _format_utc(end)}
                if i + 1 < len(self.nights):
                    next_start = self.nights[i + 1]["observing_start_utc"]
                break
            if now < start:
                next_start = n["observing_start_utc"]
                break
        return {
            "now_utc": snapshot["now_utc"],
            "local_time": (now + timedelta(hours=self.utc_offset)).strftime("%Y-%m-%d %H:%M:%S"),
            "utc_offset_hours": self.utc_offset,
            "sun_alt_deg": round(sun_alt, 2),
            "is_night": night is not None,
            "night": night,
            "next_night_start_utc": next_start,
            "min_alt_deg": self.min_alt,
            "targets": rows,
            "counts": {"decisions": self.seq, "observes": self.observes,
                       "targets_touched": len(self.observed)},
        }

    def _field(self, q: dict, now: datetime) -> dict:
        alt = float(q["alt_deg"])
        az = float(q["az_deg"]) % 360.0
        duration = q.get("duration_seconds")
        end = now + timedelta(seconds=int(duration)) if duration else None
        center_ra, center_dec = altaz_to_radec(alt, az, now, self.lat, self.lon)
        cx, cy, cz = _unit(center_ra, center_dec)  # equatorial frame, like self.vectors
        fibres = {str(f): [] for f in range(self.grid.n_fibers)}
        for t in self.targets:
            vx, vy, vz = self.vectors[t["target_id"]]
            if vx * cx + vy * cy + vz * cz < self.cos_fov:
                continue
            res = self.grid.classify_target(
                t["ra_deg"], t["dec_deg"], now, alt, az, self.lat, self.lon
            )
            if res.region != "glass" or res.alt_deg < self.min_alt:
                continue
            entry = {
                "target_id": t["target_id"], "class": t["target_class"],
                "science_weight": t["science_weight"], "feature_flux": t["feature_flux"],
                "required": bool(t["required"]),
                "alt_deg": round(res.alt_deg, 2), "az_deg": round(res.az_deg, 2),
                "observed": self.observed.get(t["target_id"], 0),
                "altitude_ok": True if end is None else altitude_ok(
                    t["ra_deg"], t["dec_deg"], now, end, self.min_alt, self.cfg),
            }
            fibres[str(int(res.fiber_id))].append(entry)
        for cands in fibres.values():
            cands.sort(key=lambda c: (
                not c["required"], -c["science_weight"], -c["feature_flux"], c["target_id"]))
        pointing_ok = None
        if end is not None:
            ra, dec = altaz_to_radec(alt, az, now, self.lat, self.lon)
            pointing_ok = altitude_ok(ra, dec, now, end, self.min_alt, self.cfg)
        return {"type": "answer", "q": "field", "alt_deg": alt, "az_deg": az,
                "duration_seconds": duration, "altitude_ok": pointing_ok, "fibres": fibres}

    def answer(self, q: dict, now: datetime) -> dict:
        kind = q.get("q")
        try:
            if kind == "field":
                return self._field(q, now)
            if kind == "autofill":
                field = self._field(q, now)
                assignments = {}
                for fid, cands in field["fibres"].items():
                    pool = [c for c in cands if c["altitude_ok"] and c["observed"] == 0]
                    if not pool:
                        pool = [c for c in cands if c["altitude_ok"] and c["observed"] < 2]
                    if pool:
                        assignments[fid] = pool[0]["target_id"]
                return {"type": "answer", "q": "autofill", "assignments": assignments}
            return {"type": "answer", "error": f"unknown query {kind!r}"}
        except Exception as exc:  # a bad query must never kill the run
            return {"type": "answer", "q": kind, "error": str(exc)[:300]}


def _bridge_factory(card: str, exchange, log: list, annotated: list, assisted: bool = False):
    """Human/assisted agent: ship snapshot+view to JS, serve queries, block for action.

    In assisted mode an in-process basic-example planner (py/console_assistant.py)
    computes a suggestion per decision; it travels with the snapshot message as
    "suggested". The UI may commit it with {"use_suggestion": true} (source
    "assistant"), accept it at a checkpoint (source "human_accept") or send any other
    action (source "human"); the committed action is always fed back via
    assistant.note() so the planner state stays consistent.
    """

    def factory(context):
        env = _BridgeEnv(card, context)
        assistant = None
        if assisted:
            from console_assistant import Assistant
            assistant = Assistant(CARD_ROOT.format(card=card))
        t0 = time.monotonic()

        def agent(snapshot):
            env.seq += 1
            now = _parse_utc(snapshot["now_utc"])
            _track_result(env, snapshot)
            suggested = assistant.suggest(env.seq, snapshot) if assistant is not None else None
            message = {"type": "snapshot", "seq": env.seq,
                       "snapshot": snapshot, "view": env.view(snapshot, now)}
            if suggested is not None:
                message["suggested"] = suggested
            while True:
                reply = exchange(json.dumps(message, default=str))
                data = json.loads(reply) if reply else {"type": "action", "action": None}
                if data.get("type") == "query":
                    message = env.answer(data, now)
                    continue
                action = suggested if data.get("use_suggestion") else data.get("action")
                if action is None:
                    log.append(None)
                    return None
                try:
                    normalized = normalize_action(action, env.scenario, env.targets_by_id, now)
                    if (normalized["action"] == "report"
                            and env.consecutive_reports >= env.max_reports):
                        raise InvalidAgentAction("too many consecutive report actions")
                except (InvalidAgentAction, ValueError) as exc:
                    message = {"type": "answer", "error": str(exc)[:300]}
                    if suggested is not None:
                        message["suggested"] = suggested  # form stays pre-filled
                    continue
                if isinstance(normalized.get("assignments"), dict):
                    normalized["assignments"] = dict(sorted(normalized["assignments"].items()))
                logged = _jsonable(normalized)
                log.append(logged)
                source = data.get("source")
                if source not in SOURCES:
                    source = "human"
                if source == "assistant" and not data.get("use_suggestion"):
                    # trust, but verify: 'assistant' means the committed action IS the suggestion
                    canon = lambda a: json.dumps(a, sort_keys=True, default=str)
                    if suggested is None or canon(logged) != canon(_jsonable(suggested)):
                        source = "human"
                annotated.append({
                    "seq": env.seq, "now_utc": snapshot["now_utc"],
                    "source": source, "action": logged,
                    "suggested": suggested,
                    "t_ms": int((time.monotonic() - t0) * 1000),
                })
                if assistant is not None:
                    assistant.note(logged)
                # Return the JSON-safe form: the runner re-validates, and e.g. a wait
                # until_utc datetime would fail its 'must end in Z' string check.
                return logged

        return agent

    return factory


def init_payload_json(card: str) -> str:
    """The PUBLIC initialize payload an AI agent would receive for this card."""
    payload = V4Workflow(Path(CARD_ROOT.format(card=card))).initialize_payload(86400)
    return json.dumps(payload, default=str)


def run_card(card: str, mode: str, actions_json: str = "[]", exchange=None, observer=None) -> str:
    log: list = []
    annotated: list = []
    if mode == "replay":
        factory = _replay_factory(json.loads(actions_json), log, observer=observer, card=card)
    elif mode in ("human", "assisted"):
        factory = _bridge_factory(card, exchange, log, annotated, assisted=(mode == "assisted"))
    else:
        raise ValueError(f"unknown mode {mode!r}")
    global _RUNS
    _RUNS += 1
    out = Path(OUTPUT_DIR.format(card=card) + f"-{_RUNS}")  # fresh dir per run in this session
    run_scenario(Path(SCENARIO_PATH.format(card=card)), factory, out)
    return json.dumps(
        {
            "score_report": (out / "score_report.json").read_text(encoding="utf-8"),
            "decisions_csv": (out / "decisions.csv").read_text(encoding="utf-8"),
            "actions": log,
            "actions_jsonl": "".join(
                json.dumps(x, ensure_ascii=False) + "\n" for x in log if x is not None),
            "annotated_log_jsonl": "".join(
                json.dumps(x, ensure_ascii=False) + "\n" for x in annotated),
        }
    )
