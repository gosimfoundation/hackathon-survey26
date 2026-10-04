#!/usr/bin/env python3
"""Agent Observer v4 reference agent ("pro"). Standard library only, participant-agent-protocol-v4.

One JSON object per line on stdin, one per line on stdout, logs on stderr.

What it does (details in README.md and planner.py):

1. Planning: every decision picks pointing, fibre assignment, duration and program together, maximising
   expected gain minus a price for telescope time (gain - lambda * T). Required targets and observation
   requests enter as probability-weighted bonuses.
2. Program: the band level is fitted to saturated hits, which show the program multiplier exactly.
3. Instrument faults: E = (quality level) / (band level). Weather moves both, a fault only the first;
   when E stays low the agent reports. Free false reports are spent early; each low episode is probed
   once; paid probes need two low nights.
4. Pace: the search level adapts to the measured cost per decision so a 4-month card fits the wall clock.
5. Model (advisor.py): at every night start a night plan (forecast + bulletin -> bad night, sectors to avoid)
   and a fault review (own quality table -> how likely a fault is, which gates paid reports); before a paid
   report the model confirms or vetoes. Calls run in the background; without an API key the agent exits.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import timedelta

from advisor import Advisor
from llm_client import LLMClient, api_key, load_dotenv
from planner import Planner
from skymath import format_utc, parse_utc

WEATHER_KINDS = {"rain", "storm", "overcast", "haze", "cold_snap"}
BAD_KINDS = {"rain", "storm", "overcast", "haze"}
PROTOCOL = "participant-agent-protocol-v4"


def _env(name: str, default: float) -> float:
    return type(default)(os.environ.get(f"PRO_{name}", default))


# --- fault reporting (see _fault_verdict) ---
E_LOW_FREE = _env("E_LOW_FREE", 0.9)      # free probe: E below this in 3 of the last 4 hours
E_LOW_FREE2 = _env("E_LOW_FREE2", 0.9)    # ... threshold while both free probes are left
E_FREE_HOURS = _env("E_FREE_HOURS", 4)
E_LOW = _env("E_LOW", 0.85)               # paid probe: low hours must span two nights ...
E_PAID_LOW = _env("E_PAID_LOW", 0.75)     # ... the median of the last 12 hourly E below this ...
E_PAID_HOURS = _env("E_PAID_HOURS", 12)
E_RECOVER = _env("E_RECOVER", 0.95)       # after a false probe, wait until E is back above this
MAX_PAID_FALSE = _env("MAX_PAID", 6)
PERSIST_NIGHTS = _env("PERSIST_NIGHTS", 3)
E_PAID_STEP = _env("E_PAID_STEP", 0.05)   # ... minus this per paid false probe so far
MAX_FALSE_REPORTS = 8
PAID_SPACING_HOURS = 20.0
MIN_REPORT_SPACING_HOURS = 2.0
# --- pace ---
PACE_SAFETY = _env("PACE_SAFETY", 0.75)
# --- model ---
MODEL_WAIT_MAX = _env("MODEL_WAIT_MAX", 20.0)   # longest wait for the night's model answers (s)
MODEL_FAULT_HIGH = _env("MODEL_FAULT_HIGH", 0.6)  # fault review at or above this: report more readily tonight
MODEL_FAULT_LOW = _env("MODEL_FAULT_LOW", 0.15)   # ... at or below this: paid reports need the strongest evidence
SCALE_STEP = _env("SCALE_STEP", 0.7)
MODEL_FREE_PROBE = _env("MODEL_FREE_PROBE", 0)   # 1: a high fault review may also spend a free probe on a low scale            # with a likely fault: report when scale stays below this x ref
FIXED_LEVEL = _env("FIXED_LEVEL", -1)     # development only: pin the search level (deterministic runs)   # spend at most this share of the remaining wall clock


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


class ObserverAgent:
    def __init__(self, init: dict):
        started = time.monotonic()
        self.planner = Planner(init, log=log)
        self.client = LLMClient(log=log)
        self.advisor = Advisor(self.client, log=log)
        self.model_wait = 0.0                    # wall seconds spent waiting for the model (not planning cost)
        self.fault_likely = None                 # tonight's model estimate that an instrument fault is active
        self.scale_hours: dict = {}              # hour -> [planner.scale samples] (for the model's fault table)
        self.start = parse_utc(init["survey"]["start_utc"])
        self.forecast_notices: list = []
        self.night_seen = None
        self.observes = 0
        # fault reporting state
        reporting = init["scoring"].get("reporting", {})
        self.free_allowance = int(reporting.get("false_report_free_allowance", 0))
        self.reports = 0
        self.correct_reports = 0
        self.false_reports = 0
        self.false_since_correct = 0
        self.paid_false = 0
        self.last_report_hours = -1e9
        self.ref_from_hours = -1e9
        self.episode_blocked = False
        self.blocked_at_hour = -1
        # pace state
        self.cost_ema = [0.0, 0.0, 0.0, 0.0]
        self.decisions = 0
        self.prev_remaining = None
        self.prev_cost = 0.0
        self.engine_ema = None
        self.sim_step_ema = None
        self.last_now = None
        log(f"pro: {len(self.planner.ids)} targets, {sum(self.planner.required)} required, "
            f"{len(self.planner.nights)} nights; init {time.monotonic() - started:.2f}s; model {self.client.model}")

    # --- decision loop ------------------------------------------------------------------------------

    def respond(self, payload: dict) -> dict:
        started = time.monotonic()
        model_before = self.model_wait
        level = self.planner.fast_level
        action = self._respond(payload)
        # waiting for the model is not planning cost: keep it out of the pace estimate
        cost = time.monotonic() - started - (self.model_wait - model_before)
        self.prev_cost = cost
        if action.get("action") == "observe" and level < 4:
            c = self.cost_ema[level]
            self.cost_ema[level] = cost if c == 0.0 else 0.9 * c + 0.1 * cost
            for k in range(level + 1, 4):   # cheaper levels not measured yet: a third of the level above
                if self.cost_ema[k] == 0.0 or self.cost_ema[k] > self.cost_ema[k - 1]:
                    self.cost_ema[k] = self.cost_ema[k - 1] / 3.0
        return action

    def _respond(self, payload: dict) -> dict:
        now = parse_utc(payload["now_utc"])
        if self.last_now is not None and self.planner.current_night(now) is not None:
            step = (now - self.last_now).total_seconds()
            if 0 < step <= 3600:
                self.sim_step_ema = step if self.sim_step_ema is None else 0.95 * self.sim_step_ema + 0.05 * step
        self.last_now = now
        hours = (now - self.start).total_seconds() / 3600.0
        planner = self.planner
        for message in payload.get("new_messages", []):
            if message.get("record_type") == "forecast":
                self.forecast_notices = message.get("notices", [])
        last = payload.get("last_result") or {}
        if last.get("action") == "report":
            self._on_report_result(last, hours)
        planner.on_messages(payload.get("new_messages", []), payload.get("latest_bulletin"))
        planner.on_requests(payload.get("active_requests", []))
        planner.on_result(payload.get("last_result"), now, hours)
        self._pace(payload, now)

        night = planner.current_night(now)
        if night is None:
            nxt = planner.next_night_start(now)
            if nxt is None:
                return {"action": "finish", "reason": "no observing night left"}
            return {"action": "wait", "until_utc": format_utc(nxt), "reason": "daytime: sleep until the next night"}
        night_index, night_start, night_end = night
        if self.night_seen != night_index:
            self.night_seen = night_index
            self._night_advice(night_start, payload, hours)
        else:
            self._apply_advice(*self.advisor.poll())
        self.scale_hours.setdefault(int(hours), []).append(self.planner.scale)
        if (night_end - now).total_seconds() < planner.min_exposure:
            nxt = planner.next_night_start(now)
            if nxt is None:
                return {"action": "finish", "reason": "survey over"}
            return {"action": "wait", "until_utc": format_utc(nxt), "reason": "night ending"}
        if planner.site_closed():
            return {"action": "wait", "duration_seconds": self._to_next_slot(now, night_start),
                    "reason": "bulletin: rain/storm over the whole sky"}
        report = self._maybe_report(hours, payload)
        if report is not None:
            return report
        action = planner.plan(now, night_end, night_index, hours)
        if action is None:
            return {"action": "wait", "duration_seconds": self._to_next_slot(now, night_start), "reason": "nothing useful is up"}
        self.observes += 1
        action["reason"] = f"{len(action['assignments'])} fibres, program {action['program']}"
        return action

    def _to_next_slot(self, now, night_start) -> int:
        slot = self.planner.slot_seconds
        into = (now - night_start).total_seconds() % slot
        return int(max(60, min(3600, slot - into)))

    # --- pace ---------------------------------------------------------------------------------------

    def _pace(self, payload: dict, now) -> None:
        """Pick the search level from the measured cost per decision and the decisions still to come."""
        wall = payload.get("wallclock") or {}
        remaining_wall = float(wall.get("remaining_seconds", 1e9))
        night_seconds = sum(max(0.0, (end - max(start, now)).total_seconds()) for start, end in self.planner.nights if end > now)
        decisions_left = max(1.0, night_seconds / (self.sim_step_ema or 900.0))   # daytime waits cost nothing
        # the wall clock also runs while the engine simulates: measure that share and leave it out
        if self.prev_remaining is not None:
            engine = (self.prev_remaining - remaining_wall) - self.prev_cost
            if 0.0 <= engine < 5.0:
                self.engine_ema = engine if self.engine_ema is None else 0.95 * self.engine_ema + 0.05 * engine
        self.prev_remaining = remaining_wall
        budget = PACE_SAFETY * remaining_wall / decisions_left - (self.engine_ema or 0.0)
        # estimates of levels not used for a while decay, so the agent climbs back up and re-measures them
        self.decisions += 1
        if self.decisions % 50 == 0:
            for k in range(4):
                if k != self.planner.fast_level:
                    self.cost_ema[k] *= 0.85
        level = 0
        if FIXED_LEVEL >= 0:
            self.planner.fast_level = FIXED_LEVEL
            return
        while level < 3 and self.cost_ema[level] > budget:
            level += 1
        if remaining_wall < 15.0:
            level = 4
        if level != self.planner.fast_level:
            log(f"pro: pace level {level} (budget {budget * 1000:.0f} ms, costs {[round(c * 1000) for c in self.cost_ema]} ms, "
                f"{decisions_left:.0f} decisions left)")
            self.planner.fast_level = level

    # --- model stages (advisor.py): night plan and fault review at every night start --------------------

    def _night_advice(self, night_start, payload: dict, hours: float) -> None:
        """Night start: rule defaults first, then the two model calls (night plan, fault review)."""
        night_date = (night_start - timedelta(hours=12)).date().isoformat()
        tonight = [n for n in self.forecast_notices if night_date in n.get("nights", [])]
        bulletin = (payload.get("latest_bulletin") or {}).get("notices", [])
        # rule defaults, kept when the model gives no valid answer
        self.planner.bad_forecast = any(n.get("direction") == "ALL" and n.get("event_kind") in BAD_KINDS for n in tonight)
        self.planner.extra_avoid = set()
        self.fault_likely = None
        left = float((payload.get("wallclock") or {}).get("remaining_seconds", 0))
        started = time.monotonic()
        answers = self.advisor.start_night(night_date, tonight, bulletin, self._fault_table(hours), left,
                                           self._model_wait_budget(payload))
        self.model_wait += time.monotonic() - started
        self._apply_advice(*answers)

    def _model_wait_budget(self, payload: dict) -> float:
        """How long the agent can afford to wait for the model at a night start: half of the wall clock the
        planner will not need, spread over the nights left (0 on a tight clock: answers then arrive later)."""
        left = float((payload.get("wallclock") or {}).get("remaining_seconds", 0))
        now = self.last_now
        nights_left = max(1, sum(1 for _, end in self.planner.nights if end > now))
        night_seconds = sum(max(0.0, (end - max(start, now)).total_seconds()) for start, end in self.planner.nights if end > now)
        decisions_left = night_seconds / (self.sim_step_ema or 900.0)
        per_decision = max(self.cost_ema[self.planner.fast_level], 0.05) + (self.engine_ema or 0.01)
        spare = left - 1.3 * decisions_left * per_decision - 30.0
        return max(0.0, min(MODEL_WAIT_MAX, 0.5 * spare / nights_left))

    def _apply_advice(self, plan, fault) -> None:
        if plan is not None:
            self.planner.bad_forecast = plan["bad_night"]
            self.planner.extra_avoid = set(plan["avoid_directions"])
            log(f"llm night plan {self.advisor.night_date}: bad_night={plan['bad_night']} avoid={plan['avoid_directions']} ({plan['reason']})")
        if fault is not None:
            self.fault_likely = fault["fault_likely"]
            log(f"llm fault review {self.advisor.night_date}: fault_likely={fault['fault_likely']:.2f} ({fault['reason']})")

    def _scale_ref(self) -> float:
        """Usual clear-sky scale since the last repair: 75th percentile of the hourly medians."""
        values = sorted(sorted(v)[len(v) // 2] for h, v in self.scale_hours.items() if h >= self.ref_from_hours and v)
        return values[(3 * len(values)) // 4] if len(values) >= 4 else 1.0

    def _fault_table(self, hours: float) -> dict:
        """The evidence the fault review reads: the last ~30 observed hours."""
        e_by_hour = {hour: sorted(v)[len(v) // 2] for hour, _, v in self.planner.e_hours if hour >= self.ref_from_hours}
        rows = []
        for hour in sorted(self.scale_hours)[-30:]:
            if hour < self.ref_from_hours:
                continue
            v = sorted(self.scale_hours[hour])
            stamp = (self.start + timedelta(hours=hour)).strftime("%m-%dT%H")
            rows.append([stamp, round(e_by_hour[hour], 2) if hour in e_by_hour else None, round(v[len(v) // 2], 2)])
        return {"columns": ["utc_hour", "E", "scale"], "rows": rows, "ref": round(self._scale_ref(), 2),
                "free_false_reports_left": max(0, self.free_left()), "paid_false_reports_so_far": self.paid_false,
                "correct_reports_so_far": self.correct_reports,
                "hours_since_last_report": None if self.reports == 0 else round(hours - self.last_report_hours, 1)}

    # --- instrument faults ---------------------------------------------------------------------------

    def _maybe_report(self, hours: float, payload: dict):
        """Report (probe) when the quality level stays below what the program bands allow.

        A report costs no time, its answer arrives at once, and the first false reports after each correct
        one are free: spend free probes readily, paid ones only on strong, lasting evidence."""
        if self.false_reports >= MAX_FALSE_REPORTS or hours - self.last_report_hours < MIN_REPORT_SPACING_HOURS:
            return None
        if self._fault_verdict(hours, payload) and self._model_agrees(hours, payload):
            self.last_report_hours = hours
            self.reports += 1
            log(f"pro: report at {payload['now_utc']} (quality below what the program bands allow), free left {self.free_left()}")
            return {"action": "report", "reason": "quality level below what the program bands allow"}
        return None

    def _fault_verdict(self, hours: float, payload: dict) -> bool:
        """Hourly E = quality level / band level (planner.e_hours). 1 = consistent; a fault keeps E low."""
        rows = [(hour, night, sorted(v)[len(v) // 2]) for hour, night, v in self.planner.e_hours if hour >= self.ref_from_hours]
        if rows and int(hours) != getattr(self, "_logged_hour", None):
            self._logged_hour = int(hours)
            log(f"pro: E {payload['now_utc']} {rows[-1][2]:.2f} scale {self.planner.scale:.3f} band {self.planner.band_level or 0:.3f}")
        if len(rows) < E_FREE_HOURS or rows[-1][0] < int(hours) - 1:
            return False
        if self.episode_blocked:
            # this low episode was probed already and was not a fault: wait for a recovery first
            last4 = rows[-4:]
            if sum(1 for _, _, e in last4 if e >= E_RECOVER) >= 3 and rows[-1][0] > self.blocked_at_hour:
                self.episode_blocked = False
                log(f"pro: quality recovered at {payload['now_utc']}; probing re-armed")
            else:
                return False
        likely = self.fault_likely
        if MODEL_FREE_PROBE and likely is not None and likely >= MODEL_FAULT_HIGH and self.free_left() > 0 and self._scale_step(hours):
            # off by default: on the practice cards it spent free probes on unannounced weather
            log(f"pro: model-flagged fault (likely {likely:.2f}) and scale below {SCALE_STEP} x ref")
            return True
        if self.free_left() > 0:
            last = rows[-E_FREE_HOURS:]
            threshold = E_LOW_FREE2 if self.free_left() >= 2 else E_LOW_FREE
            low = sum(1 for _, _, e in last if e < threshold)
            return low >= E_FREE_HOURS - 1 and last[-1][2] < threshold and last[-1][0] - last[0][0] <= E_FREE_HOURS + 3
        if self.paid_false >= MAX_PAID_FALSE or hours - self.last_report_hours < PAID_SPACING_HOURS:
            return False
        last = rows[-E_PAID_HOURS:]
        values = sorted(e for _, _, e in last)
        nights = {night for _, night, e in last if e < E_LOW}
        # a fault never goes away on its own: three low nights in a row justify a probe whatever the bar
        by_night: dict = {}
        for _, night, e in rows:
            by_night.setdefault(night, []).append(e)
        nights_seq = sorted(by_night)[-PERSIST_NIGHTS:]
        if (len(nights_seq) == PERSIST_NIGHTS and nights_seq[-1] - nights_seq[0] <= PERSIST_NIGHTS
                and all(len(by_night[n]) >= 3 and sorted(by_night[n])[len(by_night[n]) // 2] < E_LOW for n in nights_seq)
                and hours - self.last_report_hours >= 40.0):
            return True
        if likely is not None and likely <= MODEL_FAULT_LOW:
            return False   # the fault review sees weather, not a fault: only the persistence rule above may report
        # each paid false probe raises the bar for the next one
        paid_low = E_PAID_LOW - E_PAID_STEP * self.paid_false
        return (len(last) == E_PAID_HOURS and values[len(values) // 2] < paid_low and len(nights) >= 2
                and all(e < E_LOW for _, _, e in last[-3:]))

    def _scale_step(self, hours: float) -> bool:
        """The last 3 observed hours all sit below SCALE_STEP x the usual clear-sky scale."""
        recent = [sorted(v)[len(v) // 2] for h, v in sorted(self.scale_hours.items()) if h >= self.ref_from_hours and v][-3:]
        return len(recent) == 3 and max(recent) < SCALE_STEP * self._scale_ref()

    def _model_agrees(self, hours: float, payload: dict) -> bool:
        """Paid probes only: the model looks at the evidence first and may veto. Free probes cost nothing, so they
        never wait for it. No answer in time: the rule's decision stands."""
        if self.free_left() > 0:
            return True
        rows = [(hour, sorted(v)[len(v) // 2]) for hour, _, v in self.planner.e_hours if hour >= self.ref_from_hours][-24:]
        evidence = {"hourly_E_last_24h": [round(e, 2) for _, e in rows], "fault_table": self._fault_table(hours),
                    "paid_false_reports_so_far": self.paid_false, "correct_reports_so_far": self.correct_reports}
        started = time.monotonic()
        left = float((payload.get("wallclock") or {}).get("remaining_seconds", 0))
        verdict = self.advisor.confirm_report(evidence, left, min(30.0, 2.0 * self._model_wait_budget(payload)))
        self.model_wait += time.monotonic() - started
        if verdict is False:
            log(f"pro: model vetoed a paid report at {payload['now_utc']}")
            self.last_report_hours = hours
            return False
        return True

    def free_left(self) -> int:
        return self.free_allowance - self.false_since_correct

    def _on_report_result(self, result: dict, hours: float) -> None:
        if result.get("correct"):
            log(f"pro: report correct, fault repaired (delta {result.get('score_delta')})")
            self.correct_reports += 1
            self.false_since_correct = 0
            self.planner.forget_quality_history()
            self.ref_from_hours = hours
        else:
            self.false_since_correct += 1
            self.false_reports += 1
            self.episode_blocked = True
            self.blocked_at_hour = int(hours)
            if self.false_since_correct > self.free_allowance:
                self.paid_false += 1
            log(f"pro: report false (delta {result.get('score_delta')}); free left {self.free_left()}")


def main() -> int:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    if not api_key():
        print("missing API key: set OPENAI_API_KEY", file=sys.stderr, flush=True)
        return 2
    agent = None
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        kind = message.get("message_type")
        if message.get("protocol_version") != PROTOCOL:
            log(f"pro: unexpected protocol {message.get('protocol_version')!r}")
        if kind == "initialize":
            agent = ObserverAgent(message["payload"])
        elif kind == "decision_request":
            try:
                action = agent.respond(message["payload"])
            except Exception as exc:  # noqa: BLE001 - never crash the run: wait one slot instead
                log(f"pro: error {type(exc).__name__}: {exc}; waiting one slot")
                action = {"action": "wait", "duration_seconds": 900, "reason": "internal error"}
            action.setdefault("decision_source", "llm-advised")
            print(json.dumps({"protocol_version": PROTOCOL, "message_type": "decision_response",
                              "decision_sequence": message["decision_sequence"], **action}, separators=(",", ":")), flush=True)
        elif kind == "finish":
            payload = message.get("payload", {})
            log(f"pro finished: termination_reason={payload.get('termination_reason')} "
                f"observes={agent.observes if agent else 0} reports={agent.reports if agent else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
