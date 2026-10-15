#!/usr/bin/env python3
"""python-pro: a readable rule-based example agent for participant-agent-protocol-v4 (standard library only).

One JSON object per line on stdin, one per line on stdout, logs on stderr.

Per decision request:
  1. learn from the last result (planner.on_result) and from new bulletins / observation requests;
  2. daytime or rain/storm over the whole sky: wait;
  3. instrument-fault rule (FaultWatch below): report when the observed quality collapses;
  4. otherwise ask the planner (planner.py) for a greedy, required-first observe.

Optional model stage (log_reader.py): with an API key, the free-text staff notes that some cards attach to
observation requests are read once each by the model; announced closures become waits, bad sectors are
down-weighted, and announced instrument problems become reports.  Without a key, or when the platform sets
OBSERVER_MODEL_DISABLED=1 (an evaluation without a model), the agent runs on its rules alone.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import timedelta

from llm_client import LLMClient, api_key, load_dotenv
from log_reader import LogReader
from planner import N_ANCHORS, Planner
from skymath import format_utc, parse_utc

PROTOCOL = "participant-agent-protocol-v4"
NOTE_WAIT_MAX = 120.0        # longest real-time wait for the model's reading of a new staff note (s)


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


class FaultWatch:
    """A simple, conservative instrument-fault rule.

    The planner gives, after every exposure, the median of observed / predicted factor over its hits
    ("quality").  A fault multiplies the instrument efficiency by some factor until it is reported; weather
    and earthquakes lower the quality too, and a report repairs neither.  Weather changes from night to
    night, a fault stays.  So the rule compares the quality with the usual level since the last repair
    (90th percentile of exposures without all-sky weather: a clear night with a healthy instrument) and
    reports on

      * a collapse: the last COLLAPSE_RUN exposures all below COLLAPSE_LEVEL x usual, or
      * a lasting drop: the median quality of each of the last two observed nights (at least NIGHT_MIN
        exposures each, no all-sky weather) below DROP_LEVEL x usual.

    Only exposures after the last report count as evidence, so one episode is never reported twice.
    A wrong report is free for the first `false_report_free_allowance` times after each correct one and
    costs points afterwards; without free reports left the rule waits PAID_SPACING_HOURS between reports
    (a fault lasts until it is reported, so a late report still pays).
    """
    COLLAPSE_LEVEL = 0.1
    COLLAPSE_RUN = 2
    DROP_LEVEL = 0.55
    NIGHT_MIN = 4
    PAID_SPACING_HOURS = 120.0
    MIN_HISTORY = 8

    def __init__(self, free_allowance: int):
        self.free_allowance = free_allowance
        self.history: list = []          # (hours, night, quality, clean) since the last repair
        self.false_since_correct = 0
        self.last_report = -1e9
        self.reports = self.correct = 0

    def add(self, hours: float, night, quality, clean: bool) -> None:
        if quality is not None and night is not None:
            self.history.append((hours, night, quality, clean))

    def usual(self):
        """The usual quality: 90th percentile of the clean exposures since the last repair."""
        values = sorted(q for _, _, q, clean in self.history[-400:] if clean)
        return values[(9 * len(values)) // 10] if len(values) >= self.MIN_HISTORY else None

    def should_report(self, hours: float):
        usual = self.usual()
        if usual is None:
            return None
        if self.false_since_correct >= self.free_allowance and hours - self.last_report < self.PAID_SPACING_HOURS:
            return None
        fresh = [item for item in self.history if item[0] > self.last_report]   # evidence since the last report
        last = [q for _, _, q, _ in fresh[-self.COLLAPSE_RUN:]]
        if len(last) == self.COLLAPSE_RUN and max(last) < self.COLLAPSE_LEVEL * usual:
            return f"quality collapsed to {last[-1] / usual:.2f} of usual"
        nights: dict = {}
        for _, night, q, clean in fresh:
            if clean:
                nights.setdefault(night, []).append(q)
        recent = [sorted(v)[len(v) // 2] for _, v in sorted(nights.items())[-2:] if len(v) >= self.NIGHT_MIN]
        if len(recent) == 2 and max(recent) < self.DROP_LEVEL * usual:
            return f"quality at {recent[0] / usual:.2f} and {recent[1] / usual:.2f} of usual on two nights"
        return None

    def reported(self, hours: float) -> None:
        self.last_report = hours
        self.reports += 1

    def on_result(self, correct: bool) -> None:
        if correct:
            self.correct += 1
            self.false_since_correct = 0
            self.history = []            # repaired: the usual level is measured afresh
        else:
            self.false_since_correct += 1


class ObserverAgent:
    def __init__(self, init: dict, use_model: bool):
        self.planner = Planner(init, log=log)
        self.start = parse_utc(init["survey"]["start_utc"])
        reporting = init["scoring"].get("reporting", {})
        self.faults = FaultWatch(int(reporting.get("false_report_free_allowance", 0)))
        self.reader = None
        if use_model:
            client = LLMClient(log=log)
            self.reader = LogReader(client, float(init.get("site", {}).get("utc_offset_hours", 0.0)), log=log)
            log(f"python-pro: model {client.model} reads staff notes")
        self.correct_report_at = None
        self.observes = 0
        self.cpu_per_decision = 0.0

    # --- decision loop ---------------------------------------------------------------------------------

    def respond(self, payload: dict) -> dict:
        cpu_started = time.process_time()
        action = self._respond(payload)
        cost = time.process_time() - cpu_started
        self.cpu_per_decision = cost if self.cpu_per_decision == 0 else 0.95 * self.cpu_per_decision + 0.05 * cost
        return action

    def _respond(self, payload: dict) -> dict:
        now = parse_utc(payload["now_utc"])
        hours = (now - self.start).total_seconds() / 3600.0
        planner = self.planner
        last = payload.get("last_result") or {}
        if last.get("action") == "report":
            self._on_report_result(last, now, hours)
        planner.on_messages(payload.get("new_messages", []), payload.get("latest_bulletin"))
        planner.on_requests(payload.get("active_requests", []))
        planner.on_result(payload.get("last_result"))
        self.faults.add(hours, planner.quality_night, planner.last_quality, planner.quality_clean)
        self._pace(payload, now)

        night = planner.current_night(now)
        if night is None:
            start = planner.next_night_start(now)
            if start is None:
                return {"action": "finish", "reason": "no observing night left"}
            return {"action": "wait", "until_utc": format_utc(start), "reason": "daytime"}
        night_index, night_start, night_end = night

        note_action = self._read_notes(payload, now, night)
        if note_action is not None:
            return note_action
        if (night_end - now).total_seconds() < planner.min_exposure:
            start = planner.next_night_start(now)
            if start is None:
                return {"action": "finish", "reason": "survey over"}
            return {"action": "wait", "until_utc": format_utc(start), "reason": "night ending"}
        if planner.site_closed():
            return {"action": "wait", "duration_seconds": self._to_next_slot(now, night_start), "reason": "rain/storm over the whole sky"}

        why = self.faults.should_report(hours)
        if why is not None:
            self.faults.reported(hours)
            log(f"python-pro: report at {payload['now_utc']} ({why})")
            return {"action": "report", "reason": why}

        action = planner.plan(now, night_end, night_index)
        if action is None:
            return {"action": "wait", "duration_seconds": self._to_next_slot(now, night_start), "reason": "nothing useful is up"}
        self.observes += 1
        action["reason"] = f"{len(action['assignments'])} fibres, {action['duration_seconds']} s, {action['program']}"
        return action

    def _to_next_slot(self, now, night_start) -> int:
        slot = self.planner.slot_seconds
        return int(max(60, min(3600, slot - (now - night_start).total_seconds() % slot)))

    def _on_report_result(self, result: dict, now, hours: float) -> None:
        correct = bool(result.get("correct"))
        self.faults.on_result(correct)
        if correct:
            self.correct_report_at = now
            self.planner.reset_quality()
        log(f"python-pro: report {'correct, fault repaired' if correct else 'wrong'} (delta {result.get('score_delta')})")

    # --- pace ------------------------------------------------------------------------------------------

    def _pace(self, payload: dict, now) -> None:
        """Keep the planner cheap enough for the CPU budget: fewer anchors when time runs short."""
        wall = payload.get("wallclock") or {}
        cpu_left = float(wall.get("remaining_real_cpu_seconds", wall.get("remaining_seconds", 1e9)))
        night_left = sum(max(0.0, (end - max(start, now)).total_seconds()) for start, end in self.planner.nights if end > now)
        budget = 0.6 * cpu_left / max(1.0, night_left / 900.0)     # about one decision per 15 night minutes
        if self.cpu_per_decision > budget:
            self.planner.n_anchors = max(1, self.planner.n_anchors - 1)
        elif self.cpu_per_decision < 0.5 * budget and self.planner.n_anchors < N_ANCHORS:
            self.planner.n_anchors += 1

    # --- optional: staff notes read by the model (log_reader.py) -----------------------------------------

    def _read_notes(self, payload: dict, now, night):
        reader = self.reader
        if reader is None:
            return None
        requests = payload.get("active_requests", []) + [m for m in payload.get("new_messages", [])
                                                        if m.get("record_type") == "observation_request"]
        wall_left = float((payload.get("wallclock") or {}).get("wall_remaining_seconds", 1e9))
        if reader.feed(requests, now, wall_left):
            reader.wait(min(NOTE_WAIT_MAX, 0.02 * wall_left))   # waiting costs real time only, no CPU budget
        reader.collect()
        self.planner.log_avoid = reader.avoid_now(now)
        since = reader.report_due(now)
        if since is not None and (self.correct_report_at is None or self.correct_report_at < since):
            self.faults.reported((now - self.start).total_seconds() / 3600.0)
            log(f"python-pro: report at {payload['now_utc']} (staff note: instrument problem from {since:%Y-%m-%d %H:%M})")
            return {"action": "report", "reason": "staff note: instrument problem"}
        end = reader.closed(now)
        if end is not None:
            seconds = int(max(60, min((end - now).total_seconds(), (night[2] - now).total_seconds(), 3600)))
            return {"action": "wait", "duration_seconds": seconds, "reason": "staff note: site closed"}
        return None


def use_model() -> bool:
    """Model only with a key, and never when the platform runs this evaluation without a model."""
    return os.environ.get("OBSERVER_MODEL_DISABLED") != "1" and bool(api_key())


def main() -> int:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    model = use_model()
    if not model:
        log("python-pro: running on rules only (no model)")
    agent = None
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        kind = message.get("message_type")
        if kind == "initialize":
            agent = ObserverAgent(message["payload"], model)
        elif kind == "decision_request":
            try:
                action = agent.respond(message["payload"])
            except Exception as exc:  # noqa: BLE001 - never crash the run: wait one slot instead
                log(f"python-pro: error {type(exc).__name__}: {exc}; waiting")
                action = {"action": "wait", "duration_seconds": 900, "reason": "internal error"}
            action.setdefault("decision_source", "llm-advised" if model else "rules")
            print(json.dumps({"protocol_version": PROTOCOL, "message_type": "decision_response",
                              "decision_sequence": message["decision_sequence"], **action}, separators=(",", ":")), flush=True)
        elif kind == "finish":
            payload = message.get("payload", {})
            log(f"python-pro finished: {payload.get('termination_reason')}, observes {agent.observes if agent else 0}, "
                f"reports {agent.faults.reports if agent else 0} ({agent.faults.correct if agent else 0} correct)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
