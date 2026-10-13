"""Problem 2 — 宇宙线簇射阵列运行 (cosmic-ray air-shower array operations). Version v5.

v5 vs v4 (pi's v4 agents beat the reference WITHOUT any LLM: multilingual keyword lists + times/ids parsing kept
almost all of the text value): same stations, faults, storms and power cuts, but the decision-relevant facts now
live in MEANING, not in vocabulary. Messages that call for opposite actions share their keywords:
- most real ToO requests stress that they are "not a drill" (drill-words), unofficial requests name the GRB
  network (only to say it has not asked), an erroneous cancellation of a real request is later cancelled itself
  (cancel-words), and a real window may be shifted "two hours later / earlier" relative to an earlier message;
- some storm forecasts say the cell will pass well away from the array, some warnings are called off by id, and
  ETA changes come as "running two hours behind / ahead of #12";
- crews report false alarms on healthy stations using the alarm's own words.
Truth that changed: the real ToO window may differ from the first announcement (a later message moves it), and about
half of the episodes have a second real ToO window.


v4 vs v3 (pi's v3 agent parsed every message with a handful of regexes): same physics and events, but the
message channel is now written by many different people in English, Chinese, Japanese and Spanish, with
times in several formats (absolute, relative, UTC+8), corrections and withdrawals that refer to earlier messages
by number, informal second-hand storm hints, revised storm ETAs, and irrelevant chatter. Hidden seeds use
templates by different authors than the public dev seeds. Messages now carry an "id".

v3 vs v2 (pi round s2 reached 97% of the oracle by parsing every message): storm timing is genuinely
uncertain — the field mill is offline 80% of hours, warnings give the arrival with up to +-2 h error, one storm in
five arrives without a warning, and false warnings are worded and hedged exactly like real ones.

You are the shift leader of a 36-station surface array (LHAASO/Auger-like) for 7 days, deciding once per
hour. Hidden truth: each station's health (ok / drifting gain / noisy electronics / dead), thunderstorm
periods, a rare target-of-opportunity (ToO) window. Published: per-station telemetry (trigger rate,
temperature, heartbeat age — confounded by barometric pressure, sometimes stale), an electric-field mill that
is sometimes offline, and free-text shift-log / weather / power-company / ToO messages of mixed reliability.
"""
from __future__ import annotations

import math, random
import os
from aohkit.text import hedge, num, pick, hhmm
from aohkit import nl

HERE = os.path.dirname(os.path.abspath(__file__))

HOURS = 7 * 24
ROWS, COLS = "ABCDEF", 6
STATIONS = [f"{r}{c + 1}" for r in ROWS for c in range(COLS)]
BASE_RATE = 10.0          # Hz at reference pressure
BETA = 0.0075             # barometric coefficient per hPa
P0 = 600.0                # hPa (high-altitude site)
REPAIR_HOURS = 3
CREW_DISPATCHES = 10
GOOD, BAD_INCLUDED, STORM_CONTAM = 1.0, -2.0, -1.5
FAST_FACTOR, TOO_BONUS = 0.7, 5.0
DISPATCH_COST = 5.0
LLM_COST_IN, LLM_COST_OUT = 0.5, 2.0   # v5: halved (reading every message is now the point)
WALLCLOCK = 900.0


class _WinTime(nl.Time):
    """v5: a window's start and end share one time zone choice per message (v4 drew the UTC+8 marker per slot, so a
    window could mix UTC and Beijing time with a single marker at the end — ambiguous even for a careful human)."""
    MARK = {"en": [" BJT", " (Beijing time, UTC+8)", " UTC+8", " local (UTC+8)"], "zh": [" 北京时间", "（北京时间）", "（UTC+8）"],
            "ja": [" 北京時間", "（UTC+8）"], "es": [" hora de Pekín", " (UTC+8)"]}

    def __init__(self, minute, bj, mark_i):
        super().__init__(minute, tz_ok=False, rel_ok=not bj)
        self.bj, self.mark_i = bj, mark_i

    def fmt(self, lang, rng, now_min):
        if not self.bj:
            return super().fmt(lang, rng, now_min)
        marks = self.MARK[lang]
        return nl.Time(self.m + 480, tz_ok=False, rel_ok=False).fmt(lang, rng, now_min) + marks[self.mark_i % len(marks)]


class Env:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.trng = random.Random(seed * 7919 + 2)
        self._build()

    def _build(self):
        r, tr = self.rng, self.trng
        # pressure: slow weather systems (hPa)
        p, self.pressure = P0 + r.uniform(-4, 4), []
        trend = 0.0
        for h in range(HOURS):
            if h % 12 == 0:
                trend = r.uniform(-0.5, 0.5)
            p += trend + 0.6 * math.sin(2 * math.pi * h / 12) * 0.3 + r.gauss(0, 0.2)
            p = min(P0 + 12, max(P0 - 12, p))
            self.pressure.append(p)
        # thunderstorms
        self.storm = [False] * HOURS
        self.storms = []
        for _ in range(r.randint(2, 6)):
            s = r.randint(6, HOURS - 8); d = r.randint(2, 8)
            for h in range(s, min(HOURS, s + d)):
                self.storm[h] = True
            self.storms.append((s, d))
        # power outage on one row (announced, sometimes with the wrong row or time)
        self.outage = None
        if r.random() < 0.7:
            s = r.randint(10, HOURS - 10); self.outage = (r.choice(ROWS), s, r.randint(3, 6))
        # ToO window
        self.too = None
        if r.random() < 0.75:
            s = r.randint(12, HOURS - 6); self.too = (s, r.randint(2, 4), s - r.randint(2, 8))  # start, len, announced_at
        # v5: a second real ToO window in about half of the episodes (own rng: v4 truth draws unchanged)
        self.toos = [self.too] if self.too else []
        t2r = random.Random(self.seed * 130363 + 11)
        if t2r.random() < 0.5:
            for _try in range(30):
                s2 = t2r.randint(12, HOURS - 6); d2 = t2r.randint(2, 4)
                if all(s2 + d2 + 6 < a or s2 > a + d + 6 for a, d, _ in self.toos):
                    self.toos.append((s2, d2, s2 - t2r.randint(3, 8)))
                    break
        # station faults: (station, start_hour, kind); storms raise the hazard
        self.faults = {st: [] for st in STATIONS}
        for st in STATIONS:
            h = 0
            while h < HOURS:
                hz = 0.0012 * (6 if self.storm[h] else 1)
                if r.random() < hz:
                    self.faults[st].append([h, r.choice(["drift", "noisy", "dead", "dead"])])
                    h += r.randint(12, 60)
                h += 1
        for st in r.sample(STATIONS, r.randint(1, 3)):  # some stations start broken
            self.faults[st].insert(0, [0, r.choice(["drift", "noisy", "dead"])])
        self.comms_lag = {st: (r.randint(1, 3) if r.random() < 0.12 else 0) for st in STATIONS}
        self.mill_offline = set(h for h in range(HOURS) if r.random() < 0.8)
        self._build_messages()

    def _build_messages(self):
        """v5: same events as v4 (same random draws for truth), plus meaning-only distinctions (see module doc).
        nr: randomness for the v5 additions only, so v4's truth draws are unchanged."""
        r = self.rng
        mr = random.Random(self.seed * 104729 + 4)          # message-only randomness: truth stays as in v3
        nr = random.Random(self.seed * 130363 + 5)          # v5 additions
        B = nl.Board(nl.load_pool(HERE, self.seed), self.seed)
        reasons = nl.Choice({"en": ["a bright burst", "a neutrino coincidence", "a flaring blazar", "an X-ray flare"],
                             "zh": ["一个亮伽马暴", "一个中微子符合事件", "一个耀变体爆发"],
                             "ja": ["明るいバースト", "ニュートリノ同時事象", "ブレーザーのフレア"],
                             "es": ["un estallido brillante", "una coincidencia de neutrinos", "un blázar en fulguración"]})
        req_kind = lambda: "too_request_nd" if nr.random() < 0.75 else "too_request"

        def win(a_min, b_min):  # start/end of one window, same time-zone choice for both
            bj, mi = nr.random() < 0.35, nr.randrange(4)
            return _WinTime(a_min, bj, mi), _WinTime(b_min, bj, mi)
        for s, d in self.storms:
            lead = r.randint(1, 6)
            if r.random() < 0.8:  # one storm in five gets no warning
                r.uniform(0.4, 0.9)
                t0 = s - lead
                eta = s + r.choice([-2, -1, 0, 0, 1, 2])
                dur = max(1, d + mr.choice([-2, 0, 0, 2]))
                kind = "storm_warn" if mr.random() < 0.75 else "storm_warn_informal"
                if nr.random() < 0.35 and lead >= 2:  # v5: first forecast to miss, then it turns toward the array
                    w = B.add(t0, "storm_away", arrival=nl.Time(eta * 60))
                    B.add(t0 + nr.randint(1, lead - 1), "storm_turned", ref=nl.Ref(w))
                elif kind == "storm_warn":
                    w = B.add(t0, kind, arrival=nl.Time(eta * 60), dur=nl.Dur(dur, "h", approx=True))
                else:
                    w = B.add(t0, kind, arrival=nl.Time(eta * 60))
                if eta != s and mr.random() < 0.5 and s - 1 > t0:  # a later, better estimate
                    tu = mr.randint(t0 + 1, s - 1)
                    if nr.random() < 0.6:  # v5: relative to the earlier message
                        B.add(tu, "storm_later" if s > eta else "storm_earlier", ref=nl.Ref(w), delta=nl.Dur(abs(s - eta), "h"))
                    else:
                        B.add(tu, "storm_update", ref=nl.Ref(w), arrival=nl.Time(s * 60))
            B.add(s + d, "storm_clear")
        for _ in range(r.randint(2, 4)):  # false storm warnings
            h = r.randint(0, HOURS - 1)
            r.uniform(0.4, 0.9); a = r.randint(1, 6)
            informal = mr.random() >= 0.6
            u = nr.random()
            if u < 0.45:  # v5: the forecast itself says the cell will miss the array
                B.add(h, "storm_away", arrival=nl.Time((h + a) * 60))
                continue
            if informal:
                w = B.add(h, "storm_warn_informal", arrival=nl.Time((h + a) * 60))
            else:
                w = B.add(h, "storm_warn", arrival=nl.Time((h + a) * 60), dur=nl.Dur(r.randint(2, 7), "h", approx=True))
            if u < 0.8 and a > 1:  # v5: called off by id before it would arrive
                B.add(h + nr.randint(1, a - 1), "storm_miss", ref=nl.Ref(w))
        if self.outage:
            row, s, d = self.outage
            ann_row = row if r.random() < 0.8 else r.choice(ROWS)
            ann_s = s + r.choice([0, 0, 0, -1, 1, 2])
            o = B.add(max(0, s - r.randint(6, 30)), "outage_plan", row=nl.Plain(ann_row), start=nl.Time(ann_s * 60),
                      dur=nl.Dur(d, "h"))
            if ann_row != row and r.random() < 0.6:
                B.add(max(0, s - 2), "outage_correction", ref=nl.Ref(o), row=nl.Plain(row))
        for s, d, ann in self.toos:
            ann = max(0, ann)
            u = nr.random()
            if u < 0.35 and s - ann >= 2:  # v5: first announced at a shifted time, moved later by id
                sh = nr.choice([-3, -2, -1, 1, 2, 3])
                q = B.add(ann, req_kind(), **dict(zip(('start', 'end'), win((s + sh) * 60, (s + sh + d) * 60))),
                          reason=reasons)
                B.add(nr.randint(ann + 1, s - 1), "too_earlier" if sh > 0 else "too_later", ref=nl.Ref(q), delta=nl.Dur(abs(sh), "h"))
            elif u < 0.7 and s - ann >= 3:  # v5: an erroneous cancellation, then the cancellation is cancelled
                q = B.add(ann, req_kind(), **dict(zip(('start', 'end'), win(s * 60, (s + d) * 60))), reason=reasons)
                tw = nr.randint(ann + 1, s - 2)
                wd = B.add(tw, "too_withdraw", ref=nl.Ref(q))
                B.add(nr.randint(tw + 1, s - 1), "too_reinstate", ref=nl.Ref(wd))
            else:
                B.add(ann, req_kind(), **dict(zip(('start', 'end'), win(s * 60, (s + d) * 60))), reason=reasons)
        for _ in range(r.randint(1, 2)):  # drills, a cancelled request, an unauthorised look-alike
            h = r.randint(4, HOURS - 8); L = r.randint(2, 4)
            kind = r.choice(["drill", "cancel", "unauth"])
            if kind == "drill":
                B.add(h, "too_drill", **dict(zip(('start', 'end'), win((h + 2) * 60, (h + 2 + L) * 60))), reason=reasons)
            elif kind == "cancel":
                q = B.add(h, req_kind(), **dict(zip(('start', 'end'), win((h + 3) * 60, (h + 3 + L) * 60))),
                          reason=reasons)
                B.add(h + r.randint(1, 2), "too_withdraw", ref=nl.Ref(q))
            else:
                B.add(h, "too_unauth", **dict(zip(('start', 'end'), win((h + 1) * 60, (h + 1 + L) * 60))), reason=reasons)
        for _ in range(r.randint(1, 2)):  # rumours
            B.add(r.randint(0, HOURS - 6), "too_rumour")
        for st, fl in self.faults.items():  # crew/field reports, some true, some false
            for h, kind in fl:
                if r.random() < 0.45:
                    B.add(h + r.randint(0, 6), "station_issue", st=nl.Plain(st))
        for _ in range(r.randint(2, 5)):
            B.add(r.randint(0, HOURS - 1), "station_rumour", st=nl.Plain(r.choice(STATIONS)))
        for _ in range(nr.randint(2, 4)):  # v5: false alarms on stations that are healthy at that hour
            for _try in range(20):
                st, h = nr.choice(STATIONS), nr.randint(0, HOURS - 1)
                if all(start > h for start, _k in self.faults[st]):
                    B.add(h, "station_false_alarm", st=nl.Plain(st))
                    break
        for _ in range(mr.randint(8, 16)):  # irrelevant chatter
            B.add(mr.randint(0, HOURS - 1), "chatter")
        fin = B.finalize(minute_of=lambda t: max(0, t) * 60)
        self.msgs = [(m["t"], m["id"], m["text"]) for m in fin]
        self.msg_kinds = {m["id"]: (m["kind"], m["slots"]) for m in fin}  # organizer-side only (never sent)

    # -------------------------------------------------------------- truth helpers
    def status(self, st, h):
        s = "ok"
        for start, kind in self.faults[st]:
            if start <= h:
                s = kind
        for (rh, rst) in self.repairs_done:
            if rst == st and rh <= h and all(start <= rh for start, _ in self.faults[st] if start <= h):
                s = "ok"
        if self.outage and st[0] == self.outage[0] and self.outage[1] <= h < self.outage[1] + self.outage[2]:
            s = "dead"
        return s

    def _true_rate(self, st, h, s):
        rng = random.Random(self.seed * 1000003 + h * 97 + STATIONS.index(st))
        base = BASE_RATE * math.exp(-BETA * (self.pressure[h] - P0))
        if self.storm[h]:  # thunderstorm fields bias the trigger by a few percent, sign and size vary by station
            base *= 1.0 + random.Random(self.seed * 4099 + STATIONS.index(st) * 31 + h // 6).uniform(-0.06, 0.06)
        if s == "dead":
            return 0.0
        if s == "drift":
            start = max(start for start, k in self.faults[st] if start <= h)
            base *= max(0.85, 1.0 - 0.004 * (h - start))
        if s == "noisy":
            base *= rng.uniform(1.6, 4.0) if rng.random() < 0.45 else rng.uniform(0.97, 1.08)
        return max(0.0, base + rng.gauss(0, 0.35))

    # -------------------------------------------------------------- protocol
    def initialize(self):
        self.h = 0
        self.done = False
        self.mode = "normal"
        self.excluded = set()
        self.crew_queue = []    # (finish_hour, station)
        self.dispatches = 0
        self.repairs_done = []  # (hour fixed, station)
        self.ledger = []
        self.sent = 0
        self.history = []
        return {"problem": "cr_array", "version": "v5", "global_wallclock_seconds": WALLCLOCK,
                "stations": STATIONS, "layout": "6 rows A-F x 6 columns; rows share a power feeder",
                "reference": {"nominal_trigger_rate_hz": BASE_RATE, "reference_pressure_hpa": P0,
                              "barometric_note": "the trigger rate falls by roughly 0.75% per hPa of pressure increase", "muon_peak_adc_nominal": 100},
                "crew": {"dispatches_available": CREW_DISPATCHES, "repair_hours": REPAIR_HOURS, "parallel": 1},
                "scoring": {"healthy_included_station_hour": GOOD, "faulty_included_station_hour": BAD_INCLUDED,
                            "storm_hour_not_vetoed_per_included_station": STORM_CONTAM,
                            "storm_veto": "a vetoed hour scores 0 for every station",
                            "fast_mode_outside_too": f"healthy station-hours count x{FAST_FACTOR}",
                            "fast_mode_inside_too_bonus_per_healthy_included_station_hour": TOO_BONUS,
                            "dispatch_cost": -DISPATCH_COST,
                            "llm_cost_points_per_1k_tokens": {"in": LLM_COST_IN, "out": LLM_COST_OUT}}}

    def snapshot(self):
        h = self.h
        tel = []
        for st in STATIONS:
            lag = self.comms_lag[st] if (h // 24) % 2 == 0 else 0
            hh = max(0, h - lag)
            s = self.status(st, hh)
            rate = self._true_rate(st, hh, s)
            rng = random.Random(self.seed * 1000033 + h * 13 + STATIONS.index(st))
            peak = 100.0 + rng.gauss(0, 6.0)
            if s == "drift":
                start = max(st0 for st0, k in self.faults[st] if st0 <= hh)
                slope = random.Random(self.seed * 6007 + STATIONS.index(st) + start).uniform(0.004, 0.015)
                peak *= max(0.6, 1.0 - slope * (hh - start))
            tel.append({"station": st, "muon_peak_adc": None if s == "dead" else round(peak, 1), "trigger_rate_hz": None if s == "dead" and rng.random() < 0.5 else round(rate, 2),
                        "temperature_c": round(8 + 6 * math.sin(2 * math.pi * (h - 9) / 24) + rng.gauss(0, 0.5), 1),
                        "heartbeat_age_h": lag + (0 if s != "dead" else rng.randint(0, 2)),
                        "excluded": st in self.excluded})
        new = []
        while self.sent < len(self.msgs) and self.msgs[self.sent][0] <= h:
            m, mid, text = self.msgs[self.sent]
            new.append({"id": mid, "time": hhmm(max(0, m) * 60), "text": text}); self.sent += 1
        mill = None if h in self.mill_offline else round((random.Random(self.seed * 77 + h).uniform(5, 12) if self.storm[h]
                                                          else random.Random(self.seed * 77 + h).gauss(0.15, 0.4)), 2)
        return {"hour": h, "time": hhmm(h * 60), "pressure_hpa": round(self.pressure[h] + random.Random(self.seed + h).gauss(0, 0.3), 1),
                "efield_kv_per_m": mill, "telemetry": tel, "new_messages": new, "mode": self.mode,
                "crew": {"busy_until_hour": self.crew_queue[-1][0] if self.crew_queue else None,
                         "dispatches_left": CREW_DISPATCHES - self.dispatches},
                "last_hour_result": self.history[-1] if self.history else None}

    def step(self, action):
        if self.done:
            return
        h = self.h
        a = action if isinstance(action, dict) else {}
        if a.get("mode") in ("normal", "storm_veto", "fast"):
            self.mode = a["mode"]
        for st in a.get("exclude") or []:
            if st in STATIONS:
                self.excluded.add(st)
        for st in a.get("include") or []:
            self.excluded.discard(st)
        for st in (a.get("dispatch") or [])[:1]:
            if st in STATIONS and self.dispatches < CREW_DISPATCHES:
                start = max(h, self.crew_queue[-1][0] if self.crew_queue else h)
                self.crew_queue.append((start + REPAIR_HOURS, st)); self.dispatches += 1
        for fin, st in list(self.crew_queue):
            if fin <= h:
                if self.status(st, h) not in ("ok",) and not (self.outage and st[0] == self.outage[0]
                                                            and self.outage[1] <= h < self.outage[1] + self.outage[2]):
                    self.repairs_done.append((h, st))
                self.crew_queue.remove((fin, st))
        # settle this hour
        pts, healthy_inc, bad_inc = 0.0, 0, 0
        too = any(a <= h < a + d for a, d, _ in self.toos)
        for st in STATIONS:
            if st in self.excluded:
                continue
            s = self.status(st, h)
            if s == "ok":
                healthy_inc += 1
            else:
                bad_inc += 1
        if self.storm[h]:
            pts = 0.0 if self.mode == "storm_veto" else STORM_CONTAM * (healthy_inc + bad_inc)
        elif self.mode == "storm_veto":
            pts = 0.0
        else:
            f = FAST_FACTOR if self.mode == "fast" and not too else 1.0
            pts = GOOD * healthy_inc * f + BAD_INCLUDED * bad_inc
            if self.mode == "fast" and too:
                pts += TOO_BONUS * healthy_inc
        self.ledger.append(pts)
        self.history.append({"hour": h, "mode": self.mode, "included": 36 - len(self.excluded)})
        self.h += 1
        if self.h >= HOURS:
            self.done = True

    def score_report(self, llm):
        llm_cost = LLM_COST_IN * llm.get("tokens_in", 0) / 1000 + LLM_COST_OUT * llm.get("tokens_out", 0) / 1000
        data = sum(self.ledger)
        total = data - DISPATCH_COST * self.dispatches - llm_cost
        best = 0.0
        for h in range(HOURS):  # rough upper reference: oracle exclusion + veto + ToO, no repairs
            ok = sum(1 for st in STATIONS if self.status(st, h) == "ok")
            too = any(a <= h < a + d for a, d, _ in self.toos)
            best += 0 if self.storm[h] else ok * (1 + (TOO_BONUS if too else 0))
        return {"total": round(total, 1), "data_points": round(data, 1), "dispatches": self.dispatches,
                "repairs_effective": len(self.repairs_done), "storm_hours": sum(self.storm), "llm_cost": round(llm_cost, 1),
                "oracle_no_repair_reference": round(best, 1)}


# action applied for every decision after the agent crashed or ran out of wall clock (scores 0)
IDLE_ACTION = {"type": "ops", "mode": "storm_veto"}


def make_env(seed: int) -> Env:
    return Env(seed)
