"""Problem 3 — 超新星中微子爆发预警 (supernova neutrino burst early warning). Version v4.

v4 vs v3 (pi's v3 agent read notices with keyword lists + one time regex): same physics and events, but every
message and every check reply is written by many different people in English/Chinese/Japanese/Spanish (aohkit/nl.py),
some calibration times are announced wrong and then moved by reference to the earlier message, and a look-alike
appears: a clock fault on an offline test bench (no effect on live data), often right around a real burst — a
keyword reader that treats it as a network glitch throws away a real supernova. NEW in v4: pipeline-test injections
(1-2 per seed) that are identical to a burst in the data but not part of the scored exercise (alerting on one is a
false alert); coordination announces them on the channel (usually before, sometimes 1-2 steps after). Look-alikes:
alert-system tests that inject nothing, and announced pipeline tests that are later cancelled — both placed around
real bursts. Hidden seeds use different authors.

v3 vs v2 (lead review: one binary burst per seed made the score mostly luck): the episode is a 4-day SNEWS-style
exercise period with 3-5 unannounced injected bursts (graded distances, directions, some with a pre-supernova
ramp), so every seed has several graded opportunities; all v2 traps (timing glitches, SK pointing on fakes, huge
IceCube noise storms, radon ramps, outages) remain and scale with the longer watch.

v2 vs v1 (pi round s1 found two give-aways): Super-K publishes a pointing estimate for ANY large SK excess (fakes
get a random direction), IceCube noise storms can be as large as a distant burst, and network-wide timing glitches
produce coincident excesses whose arrival times look physically consistent — they are only identifiable from the
text notices (sometimes posted one step late) or a check.

You are the duty officer of a SNEWS-like network of four detectors for 48 hours, deciding every 15 minutes.
Hidden truth: whether a core-collapse burst happens and when, its distance and direction, whether a
pre-supernova neutrino ramp precedes it, which single-detector excesses are calibrations / spallation /
electronics noise. Published: per-detector burst-search statistics, detector status lines, free-text shift and
astronomy messages, and after any large excess, arrival-time offsets and (sometimes) a Super-K pointing estimate.
"""
from __future__ import annotations

import math, os, random
from aohkit.text import hedge, num, pick, hhmm
from aohkit import nl

HERE = os.path.dirname(os.path.abspath(__file__))

STEP_MIN = 15
STEPS = 4 * 24 * 4
C_KM_MS = 299.792458
DETECTORS = {   # fixed frame positions (km) — the problem uses this frame for directions
    "SK": (-3920.0, 3360.0, 3700.0), "KamLAND": (-3780.0, 3480.0, 3770.0),
    "JUNO": (-2320.0, 5000.0, 2380.0), "IceCube": (0.0, 0.0, -6357.0)}
BKG = {"SK": 1.2, "KamLAND": 0.4, "JUNO": 1.5, "IceCube": 3.0}       # mean counts per 10-s window
YIELD10 = {"SK": 7000, "KamLAND": 300, "JUNO": 5000, "IceCube": 2.0e5}  # burst counts at 10 kpc (IceCube: hit excess)
TIMING_MS = {"SK": 1.5, "KamLAND": 4.0, "JUNO": 1.5, "IceCube": 1.0}
R_BURST, R_LATE_STEP = 1000.0, 0.25
MISS = -500.0
FALSE_BURST = -750.0
DIR_MAX = 400.0
PRE_MAX, PRE_FALSE = 500.0, -250.0
CHECK_COST, CHECKS = 20.0, 12
CREDIT_STEPS = 4  # a burst alert counts for a burst if issued within 4 steps (1 h) after it
LLM_COST_IN, LLM_COST_OUT = 1.0, 4.0
WALLCLOCK = 900.0


def unit(ra, dec):
    a, d = math.radians(ra), math.radians(dec)
    return (math.cos(d) * math.cos(a), math.cos(d) * math.sin(a), math.sin(d))


def ang(u, v):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(u, v))))))


class Env:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.trng = random.Random(seed * 7919 + 3)
        self._build()

    def _build(self):
        r, tr = self.rng, self.trng
        self.bursts = []
        k = r.randint(3, 5)
        slots = sorted(r.sample(range(1, (STEPS - 12) // 36), k))
        for j in slots:
            step = j * 36 + r.randint(0, 20)
            dist = r.choice([r.uniform(0.2, 1.0), r.uniform(1.5, 5), r.uniform(5, 15), r.uniform(15, 30), r.uniform(45, 65)])
            ra, dec = r.uniform(0, 360), math.degrees(math.asin(r.uniform(-1, 1)))
            pre = dist < 1.2 and r.random() < 0.85  # only a very close progenitor gives a pre-SN neutrino ramp
            self.bursts.append({"step": step, "dist": dist, "ra": ra, "dec": dec, "pre": pre,
                                "pre_start": step - r.randint(8, 24) if pre else None})
        self.burst = None
        # downtime windows (announced in status lines, sometimes extended silently)
        self.down = {d: set() for d in DETECTORS}
        for d in DETECTORS:
            if r.random() < 0.55:
                s = r.randint(0, STEPS - 10); L = r.randint(6, 40)
                self.down[d].update(range(s, min(STEPS, s + L)))
                if r.random() < 0.3:
                    self.down[d].update(range(s + L, min(STEPS, s + L + r.randint(2, 6))))  # silent overrun
        # single-detector false excesses
        self.fakes = []  # (step, det, kind, counts, announced)
        for _ in range(r.randint(5, 12)):
            d = r.choice(list(DETECTORS)); s = r.randint(0, STEPS - 1)
            kind = {"SK": "spallation", "KamLAND": "radon", "JUNO": "calibration", "IceCube": "noise_storm"}[d]
            if r.random() < 0.3:
                kind = "calibration"
            counts = {"spallation": r.randint(10, 30), "radon": r.randint(6, 15), "calibration": r.randint(150, 2000),
                      "noise_storm": r.randint(60, 400) if r.random() < 0.6 else r.randint(3000, 15000)}[kind]
            self.fakes.append((s, d, kind, counts, r.random() < 0.6))
        for _ in range(r.choice([1, 2, 2, 3])):  # coincident pairs of unrelated fakes in the same window
            s = r.randint(0, STEPS - 1)
            for d in r.sample(list(DETECTORS), 2):
                kind = {"SK": "spallation", "KamLAND": "radon", "JUNO": "calibration", "IceCube": "noise_storm"}[d]
                self.fakes.append((s, d, kind, {"spallation": r.randint(25, 60), "radon": r.randint(30, 60),
                                                "calibration": r.randint(150, 800), "noise_storm": r.randint(100, 400)}[kind],
                                   r.random() < 0.35))
        # network timing glitch: 2-3 detectors fire together with near-consistent times (text notice, maybe late)
        self.glitches = []
        for _ in range(r.choice([1, 2, 2, 3])):
            s = r.randint(4, STEPS - 4)
            dets = r.sample(list(DETECTORS), r.choice([2, 2, 3]))
            for d in dets:
                self.fakes.append((s, d, "glitch", int(r.uniform(8, 25) * (BKG[d] + 1) * (40 if d == "IceCube" else 3)), False))
            self.glitches.append((s, dets, r.choice([0, 0, 1, 1, 2])))
        # KamLAND radon episode: a slow singles-rate ramp that mimics a pre-supernova signal (KamLAND only)
        self.radon_ramp = None
        if r.random() < 0.35:
            s0 = r.randint(0, STEPS - 30); self.radon_ramp = (s0, s0 + r.randint(10, 24), r.random() < 0.5)
        # v4: pipeline-test injections — identical to a burst in the data, NOT part of the scored exercise
        xr = random.Random(self.seed * 7 + 11)
        self.tests = []
        for _ in range(xr.choice([1, 1, 2])):
            for _try in range(50):
                st = xr.randint(6, STEPS - 8)
                if all(abs(st - b["step"]) >= 12 for b in self.bursts) and all(abs(st - t["step"]) >= 12 for t in self.tests):
                    self.tests.append({"step": st, "dist": xr.uniform(1.5, 15), "ra": xr.uniform(0, 360),
                                       "dec": math.degrees(math.asin(xr.uniform(-1, 1))), "pre": False, "pre_start": None,
                                       "announce": xr.choice(["before", "before", "before", "after1", "after1", "after2"]),
                                       "lead": xr.randint(1, 8)})
                    break
        self._build_msgs()

    def _build_msgs(self):
        """v4: same events as v3 (same random draws decide them); written by many people in 4 languages
        (aohkit/nl.py); calibration times sometimes announced wrong and corrected by reference; and a look-alike:
        a timing fault on an offline test bench (no effect on live data), sometimes right around a real burst."""
        r = self.rng
        mr = random.Random(self.seed * 104729 + 6)
        self.pool = nl.load_pool(HERE, self.seed)
        B = nl.Board(self.pool, self.seed)
        T = lambda st: nl.Time(max(0, st) * STEP_MIN)
        names = {"SK": ["Super-K", "SK", "Super-Kamiokande"], "KamLAND": ["KamLAND"], "JUNO": ["JUNO"], "IceCube": ["IceCube", "ICECUBE", "IC"]}
        D = lambda d: nl.Plain(mr.choice(names[d]))
        causes = {"spallation": {"en": ["a muon-induced spallation cluster", "spallation after a big muon shower"], "zh": ["宇宙线缪子散裂事例簇"], "ja": ["ミューオン起因の破砕事象クラスター"], "es": ["un cúmulo de espalación inducido por muones"]},
                  "radon": {"en": ["radon intrusion after pump work"], "zh": ["抽泵后氡渗入"], "ja": ["ポンプ作業後のラドン混入"], "es": ["intrusión de radón tras trabajos en la bomba"]},
                  "noise_storm": {"en": ["a PMT noise storm", "a burst of PMT dark noise"], "zh": ["光电倍增管噪声暴"], "ja": ["PMTノイズストーム"], "es": ["una tormenta de ruido en los PMT"]},
                  "calibration": {"en": ["a calibration source run"], "zh": ["刻度源运行"], "ja": ["較正線源ラン"], "es": ["una calibración con fuente"]},
                  "glitch": {"en": ["a clock/timing glitch that produced spurious triggers"], "zh": ["时钟故障引起的假触发"], "ja": ["クロック異常による偽トリガー"], "es": ["un fallo de reloj que produjo disparos espurios"]},
                  "reboot": {"en": ["an electronics crate reboot"], "zh": ["电子学机箱重启"], "ja": ["エレクトロニクスクレートの再起動"], "es": ["un reinicio del crate de electrónica"]}}
        self.causes = causes
        for s, d, kind, c, ann in self.fakes:
            if ann and kind == "calibration":
                t0 = s - r.randint(1, 6); r.random()
                if mr.random() < 0.4:  # first announced at the wrong time, then moved (by reference)
                    wrong = s + mr.choice([-6, -5, -4, 4, 5, 6, 8])
                    a = B.add(t0 - mr.randint(2, 8), "calib_plan", det=D(d), at=T(wrong))
                    B.add(t0, "calib_moved", ref=nl.Ref(a), at=T(s))
                else:
                    B.add(t0, "calib_plan", det=D(d), at=T(s))
            elif ann:
                st = s + r.randint(0, 2); r.random()
                B.add(st, "det_artifact", det=D(d), cause=nl.Choice(causes[kind if kind in causes else "reboot"]))
        for d, steps in self.down.items():
            if steps:
                s0 = min(steps); e = max(steps)
                B.add(s0 - r.randint(0, 4), "maintenance", det=D(d), start=T(s0), dur=nl.Dur((e - s0 + 1) * STEP_MIN / 60, "h", nd=1, approx=True))
        for _ in range(r.randint(1, 3)):  # astronomy red herrings
            st = r.randint(0, STEPS - 1); r.random()
            k = mr.choice(["astro_speculation", "astro_speculation", "rumour_burst"])
            if k == "astro_speculation":
                B.add(st, k, star=nl.Plain(mr.choice(["Betelgeuse", "Antares", "VY Canis Majoris", "Eta Carinae"])))
            else:
                B.add(st, k)
        for s, dets, delay in self.glitches:
            B.add(s + delay, "glitch_notice", at=T(s), dets=nl.Plain(", ".join(mr.choice(names[d]) for d in dets)))
            r.random(); r.random()
        if self.radon_ramp and self.radon_ramp[2]:
            B.add(self.radon_ramp[0] + r.randint(1, 5), "radon_notice"); r.random()
        B.add(0, "exercise_notice")
        for b in self.bursts:
            if b["pre"] and r.random() < 0.5:
                B.add(b["pre_start"] + r.randint(2, 6), "pre_sn_hint"); r.random()
        for _ in range(mr.randint(1, 2)):  # look-alike: test-bench clock fault (often right around a real burst)
            if self.bursts and mr.random() < 0.6:
                st = mr.choice(self.bursts)["step"] + mr.choice([-1, 0, 0, 1])
            else:
                st = mr.randint(4, STEPS - 4)
            B.add(st + mr.randint(0, 2), "glitch_testbed", at=T(st),
                  dets=nl.Plain(", ".join(mr.choice(names[d]) for d in mr.sample(list(DETECTORS), mr.choice([2, 2, 3])))))
        for t in self.tests:  # announcements of pipeline-test injections (usually before, sometimes just after)
            if t["announce"] == "before":
                B.add(t["step"] - t["lead"], "pipeline_test", at=T(t["step"]))
            else:
                B.add(t["step"] + (1 if t["announce"] == "after1" else 2), "pipeline_test_after", at=T(t["step"]))
        for _ in range(mr.randint(1, 2)):  # look-alikes around real bursts: alert-system test (no data), cancelled test
            if not self.bursts:
                break
            b = mr.choice(self.bursts)
            if mr.random() < 0.5:
                B.add(b["step"] - mr.randint(1, 6), "alert_system_test", at=T(b["step"] + mr.choice([0, 0, 1])))
            else:
                q = B.add(b["step"] - mr.randint(10, 20), "pipeline_test", at=T(b["step"]))
                B.add(b["step"] - mr.randint(2, 8), "test_cancelled", ref=nl.Ref(q))
        for _ in range(mr.randint(10, 20)):
            B.add(mr.randint(0, STEPS - 1), "chatter")
        fin = B.finalize(minute_of=lambda t: max(0, t) * STEP_MIN)
        self.msgs = [(m["t"], m["id"], m["text"]) for m in fin]
        self.msg_kinds = {m["id"]: (m["kind"], m["slots"]) for m in fin}  # organizer-side only (never sent)
        self.reply_board = nl.Board(self.pool, self.seed, salt=1)
        self.next_id = len(fin) + 1

    # ---------------------------------------------------------------- truth helpers
    def _running(self, d, s):
        return s not in self.down[d]

    def _stats(self, d, s):
        rng = random.Random(self.seed * 1000003 + s * 11 + list(DETECTORS).index(d))
        if not self._running(d, s):
            return None
        bkg = BKG[d]
        # max over 90 ten-second windows of Poisson(bkg)
        mx = max(self._poisson(rng, bkg) for _ in range(90))
        note = []
        b = next((x for x in self.bursts if x["pre"] and x["pre_start"] <= s < x["step"]), None)
        if b and d in ("KamLAND", "JUNO"):
            frac = (s - b["pre_start"]) / max(1, b["step"] - b["pre_start"])
            ibd = 0.4 + (0.2 + 1.6 * frac ** 2) / b["dist"]
            note.append(round(ibd + rng.gauss(0, 0.15), 2))
        elif d == "KamLAND" and self.radon_ramp and self.radon_ramp[0] <= s < self.radon_ramp[1]:
            frac = (s - self.radon_ramp[0]) / max(1, self.radon_ramp[1] - self.radon_ramp[0])
            note.append(round(0.4 + 1.8 * frac + rng.gauss(0, 0.15), 2))
        else:
            note.append(round(max(0.0, rng.gauss(0.4, 0.15)), 2))
        for bb in self.bursts + self.tests:  # v4: test injections look exactly like bursts
            if s == bb["step"]:
                mx += int(YIELD10[d] * (10.0 / bb["dist"]) ** 2 * rng.uniform(0.85, 1.15))
        for fs, fd, kind, c, _ in self.fakes:
            if fs == s and fd == d:
                mx += c
        return {"max_10s_counts": mx, "mean_bkg_per_10s": bkg, "ibd_singles_rate_per_h": note[0]}

    @staticmethod
    def _poisson(rng, lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1

    # ---------------------------------------------------------------- protocol
    def initialize(self):
        self.s = 0
        self.done = False
        self.alerts = []  # (step, level, direction or None)
        self.checks = 0
        self.check_replies = []
        self.sent = 0
        return {"problem": "sn_burst_v4", "version": "v4", "global_wallclock_seconds": WALLCLOCK, "step_minutes": STEP_MIN,
                "steps": STEPS, "detectors": {d: {"position_km_fixed_frame": DETECTORS[d], "timing_resolution_ms": TIMING_MS[d],
                                                  "mean_background_per_10s": BKG[d]} for d in DETECTORS},
                "frame_note": "directions are unit vectors / (ra, dec) in the fixed frame of position_km_fixed_frame; a "
                              "neutrino from direction n reaches detector i at t0 - (r_i . n)/c",
                "scoring": {"per_injected_burst": "each burst is scored separately; a burst alert is credited to a burst if issued within 4 steps after it",
                            "burst_alert_on_time": R_BURST, "late_per_step": f"-{int(R_LATE_STEP * 100)}% per 15-min step late",
                            "missed_burst": MISS, "false_burst_alert": FALSE_BURST,
                            "direction_bonus": f"{DIR_MAX} x max(0, 1 - error_deg/60)",
                            "pre_supernova_alert": f"up to {PRE_MAX} (full if >= 2 h before the burst)", "false_pre_alert": PRE_FALSE,
                            "detector_check": f"-{CHECK_COST} each, at most {CHECKS}",
                            "llm_cost_points_per_1k_tokens": {"in": LLM_COST_IN, "out": LLM_COST_OUT}}}

    def snapshot(self):
        s = self.s
        det = {}
        for d in DETECTORS:
            st = self._stats(d, s - 1) if s > 0 else None
            det[d] = {"running": self._running(d, max(0, s - 1)) if s > 0 else self._running(d, 0), "last_window": st}
        excess = {d: v["last_window"]["max_10s_counts"] for d, v in det.items()
                  if v["last_window"] and v["last_window"]["max_10s_counts"] >= 30}
        timing = None
        if len(excess) >= 1 and s > 0:
            rng = random.Random(self.seed * 99991 + s)
            b = next((x for x in self.bursts + self.tests if x["step"] == s - 1), None)
            if b:
                n = unit(b["ra"], b["dec"])
                t0 = rng.uniform(0, 900000)
                timing = {d: round(t0 - sum(a * c for a, c in zip(DETECTORS[d], n)) / C_KM_MS + rng.gauss(0, TIMING_MS[d]), 2)
                          for d in excess if self._running(d, s - 1) and det[d]["last_window"]["max_10s_counts"] >= 0.5 * YIELD10[d] * (10.0 / b["dist"]) ** 2}
            else:
                gl = [g for g in self.glitches if g[0] == s - 1]
                if gl:
                    t0 = rng.uniform(0, 900000)
                    timing = {d: round(t0 + rng.uniform(-15, 15), 2) if d in gl[0][1] else round(rng.uniform(0, 900000), 2) for d in excess}
                else:
                    timing = {d: round(rng.uniform(0, 900000), 2) for d in excess}
        sk_point = None
        b = next((x for x in self.bursts + self.tests if x["step"] == s - 1), None)
        skw = det["SK"]["last_window"]
        if skw and skw["max_10s_counts"] >= 30 and not (b and b["step"] == s - 1):
            rng = random.Random(self.seed * 4243 + s)
            sk_point = {"ra_deg": round(rng.uniform(0, 360), 1), "dec_deg": round(math.degrees(math.asin(rng.uniform(-1, 1))), 1),
                        "error_deg_1sigma": round(rng.uniform(4, 25), 1)}
        if b and b["step"] == s - 1 and self._running("SK", s - 1) and b["dist"] < 30:
            rng = random.Random(self.seed * 4243 + 17 * s)
            err = 3 + 0.5 * b["dist"]
            ra = b["ra"] + rng.gauss(0, err) / max(0.2, math.cos(math.radians(b["dec"])))
            dec = max(-90, min(90, b["dec"] + rng.gauss(0, err)))
            sk_point = {"ra_deg": round(ra % 360, 1), "dec_deg": round(dec, 1), "error_deg_1sigma": round(err, 1)}
        new = []
        while self.sent < len(self.msgs) and self.msgs[self.sent][0] <= s:
            m, mid, text = self.msgs[self.sent]
            new.append({"id": mid, "time": hhmm(max(0, m) * STEP_MIN), "text": text}); self.sent += 1
        due = [c for c in self.check_replies if c["_due"] <= s]
        self.check_replies = [c for c in self.check_replies if c["_due"] > s]
        new += [{"id": c["id"], "time": c["time"], "text": c["text"]} for c in due]
        return {"step": s, "time": hhmm(s * STEP_MIN), "detectors": det,
                "excess_arrival_ms": timing, "sk_elastic_pointing": sk_point, "new_messages": new,
                "checks_left": CHECKS - self.checks}

    def step(self, action):
        if self.done:
            return
        a = action if isinstance(action, dict) else {}
        t = a.get("type")
        if t == "alert" and a.get("level") in ("burst", "pre_sn"):
            dirn = None
            dd = a.get("direction")
            if isinstance(dd, dict):
                try:
                    dirn = (float(dd["ra"]), float(dd["dec"]))
                except (KeyError, TypeError, ValueError):
                    dirn = None
            self.alerts.append((self.s, a["level"], dirn))
        elif t == "check" and a.get("detector") in DETECTORS and self.checks < CHECKS:
            self.checks += 1
            d = a["detector"]
            s = self.s - 1
            reason, kind = None, "check_reply_clear"
            for fs, fd, fk, c, _ in self.fakes:
                if fd == d and abs(fs - s) <= 1:
                    reason, kind = fk, "check_reply_cause"
            if not self._running(d, max(0, s)):
                reason, kind = None, "check_reply_offline"
            slots = {"det": nl.Plain(d)}
            if kind == "check_reply_cause":
                slots["cause"] = nl.Choice(self.causes[reason])
            text = self.reply_board.render(kind, slots, self.s * STEP_MIN)
            self.msg_kinds[self.next_id] = (kind, slots)
            self.check_replies.append({"id": self.next_id, "time": hhmm(self.s * STEP_MIN), "text": text, "_due": self.s + 1})
            self.next_id += 1
        self.s += 1
        if self.s >= STEPS:
            self.done = True

    def score_report(self, llm):
        pts, detail = 0.0, []
        bursts = sorted(x for x in self.alerts if x[1] == "burst")
        used = set()
        for b in self.bursts:
            hit = [x for x in bursts if b["step"] + 1 <= x[0] <= b["step"] + 1 + CREDIT_STEPS and x not in used]
            if hit:
                x = hit[0]; used.add(x)
                late = x[0] - (b["step"] + 1)
                pts += R_BURST * max(0.0, 1 - R_LATE_STEP * late)
                msg = f"burst@{b['step']} ({b['dist']:.1f} kpc): alert {late} steps late"
                if x[2]:
                    err = ang(unit(*x[2]), unit(b["ra"], b["dec"]))
                    pts += DIR_MAX * max(0.0, 1 - err / 60.0); msg += f", direction error {err:.1f} deg"
                detail.append(msg)
            else:
                pts += MISS; detail.append(f"burst@{b['step']} ({b['dist']:.1f} kpc): missed")
        windows = [(b["step"] + 1, b["step"] + 1 + CREDIT_STEPS) for b in self.bursts]
        groups = []  # unmatched burst alerts outside every credit window; alerts within 8 steps merge
        for x in bursts:
            if x in used or any(a <= x[0] <= e for a, e in windows):
                continue
            if not groups or x[0] - groups[-1] > 8:
                groups.append(x[0])
        pts += FALSE_BURST * len(groups)
        if groups:
            detail.append(f"{len(groups)} false burst alert(s)")
        pres = sorted(x for x in self.alerts if x[1] == "pre_sn")
        credited = set()
        for b in self.bursts:
            if not b["pre"]:
                continue
            hit = [x for x in pres if b["pre_start"] <= x[0] <= b["step"]]
            if hit:
                lead_h = (b["step"] - hit[0][0]) * STEP_MIN / 60
                pts += PRE_MAX * min(1.0, lead_h / 2.0); detail.append(f"pre-SN alert {lead_h:.1f} h ahead of burst@{b['step']}")
                credited.update(hit)
        fgroups = []
        for x in pres:
            if x in credited:
                continue
            if not fgroups or x[0] - fgroups[-1] > 8:
                fgroups.append(x[0])
        pts += PRE_FALSE * len(fgroups)
        if fgroups:
            detail.append(f"{len(fgroups)} false pre-SN alert(s)")
        pts -= CHECK_COST * self.checks
        llm_cost = LLM_COST_IN * llm.get("tokens_in", 0) / 1000 + LLM_COST_OUT * llm.get("tokens_out", 0) / 1000
        total = pts - llm_cost
        best = sum(R_BURST + DIR_MAX + (PRE_MAX if b["pre"] else 0) for b in self.bursts)
        return {"total": round(total, 1), "bursts": len(self.bursts), "pre_sn_signals": sum(1 for b in self.bursts if b["pre"]),
                "detail": detail, "checks": self.checks, "llm_cost": round(llm_cost, 1), "max_possible": best}


# action applied for every decision after the agent crashed or ran out of wall clock (scores 0)
IDLE_ACTION = {"type": "wait"}


def make_env(seed: int) -> Env:
    return Env(seed)
