"""Problem 4 — 振荡实验运行 (reactor neutrino oscillation experiment operations). Version v3.

v3 vs v2 (pi's v2 agent read the text with a few keywords): same physics and events, but every message is now
written by many different people in English/Chinese/Japanese/Spanish, corrections refer to earlier messages by id,
and look-alike messages need understanding (far-away unfelt quakes, harmless temperature wiggles outside the liquid
scintillator, HV trips on veto PMTs only). The n-capture peak is noisier still (0.020 MeV per block) and scale-changing
events are more frequent (2-5), so knowing WHEN something happened is worth more. Hidden seeds use templates by different authors than dev seeds.

v2 vs v1 (pi round s1 scored the same with or without reading any message): the per-block n-capture peak is
noisier (one block no longer reveals a scale jump), flasher readings overlap the noise, and the shift log /
slow-control / seismology text therefore carries the timing information that pays.

You are run coordinator of a JUNO-like reactor antineutrino detector for 30 days, deciding every 6 hours.
Hidden truth: the detector energy scale (slow drift + jumps after events), reactor cores' real power
(refuelling outages announced in prose, sometimes wrong or corrected), PMT flasher episodes, a water-pool leak.
Published: per-block data summaries (IBD count, n-capture peak position, hit-pattern anomaly), and free text from
the power company, slow control, seismology, the run-coordination channel and rumours.
"""
from __future__ import annotations

import math, os, random
from aohkit.text import hedge, num, pick
from aohkit import nl

HERE = os.path.dirname(os.path.abspath(__file__))

BLOCK_H = 6
BLOCKS = 30 * 4
CORES = ["Taishan-1", "Taishan-2", "Yangjiang-1", "Yangjiang-2", "Yangjiang-3", "Yangjiang-4"]
NC_PEAK = 2.223  # MeV
NC_NOISE = 0.020  # MeV per block (v2: 0.010) — a single scale jump is hard to see in the data alone
W_PHYS = 10.0
BKG_BONUS, BKG_CAP = 8.0, 12
FLASHER_PENALTY = 15.0
LLM_COST_IN, LLM_COST_OUT = 0.5, 2.0  # v3: halved (this problem's total is ~1000)
WALLCLOCK = 900.0


def block_label(b):
    d, q = divmod(b, 4)
    return f"day {d + 1} {q * BLOCK_H:02d}:00"


class Env:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.trng = random.Random(seed * 7919 + 4)
        self._build()

    def _build(self):
        r, tr = self.rng, self.trng
        # reactor outages (real) and their announcements
        self.core_off = {c: set() for c in CORES}
        self.outages = []
        center = r.randint(20, BLOCKS - 30)  # refuelling campaigns cluster in time
        for c in r.sample(CORES, r.randint(1, 3)):
            s = max(2, center + r.randint(-14, 14)); L = r.randint(8, 28)
            self.core_off[c].update(range(s, min(BLOCKS, s + L)))
            self.outages.append((c, s, L))
        if r.random() < 0.4:  # unplanned scram
            c = r.choice(CORES); s = r.randint(0, BLOCKS - 6); L = r.randint(2, 6)
            self.core_off[c].update(range(s, min(BLOCKS, s + L))); self.outages.append((c, s, L, "scram"))
        # events that shift the energy scale
        self.events = []  # (block, kind, jump)
        for _ in range(r.randint(2, 5)):  # v3: more scale-changing events (v2: 1-4)
            self.events.append((r.randint(2, BLOCKS - 2), r.choice(["temperature", "temperature", "earthquake", "hv_trip"]),
                                r.choice([-1, 1]) * r.uniform(0.004, 0.012)))
        self.events.sort()
        # flasher episodes and a possible water leak
        self.flash_start = sorted(r.sample(range(3, BLOCKS - 3), r.randint(1, 3)))
        self.leak_start = r.randint(10, BLOCKS - 10) if r.random() < 0.4 else None
        self.drift_rate = r.uniform(-0.0001, 0.0001)  # v3: slow drift (v2: +-0.0004) — jumps dominate
        self._build_msgs()

    def _build_msgs(self):
        """v3: same events as v2 (decided with the same random draws); written by many people in 4 languages
        (aohkit/nl.py), plus look-alike messages that need reading: far-away unfelt quakes, harmless temperature
        wiggles outside the liquid scintillator, HV trips on water-pool veto PMTs only."""
        r = self.rng
        mr = random.Random(self.seed * 104729 + 8)
        B = nl.Board(nl.load_pool(HERE, self.seed), self.seed)
        T = lambda b: nl.Time(max(0, b) * BLOCK_H * 60)
        for o in self.outages:
            c, s, L = o[0], o[1], o[2]
            if len(o) == 4:  # scram: reported after the fact, sometimes
                if r.random() < 0.6:
                    B.add(s + r.randint(1, 3), "scram", core=nl.Plain(c), at=T(s), restart=nl.Dur(L * 6, "h"))
                continue
            ann_s = s + r.choice([0, 0, -2, 2, 4]); ann_L = L + r.choice([0, 0, -4, 4, 8])
            o1 = B.add(max(0, s - r.randint(8, 40)), "outage_plan", core=nl.Plain(c), start=T(ann_s),
                       dur=nl.Dur(ann_L * 6 / 24, "d", nd=1, approx=True))
            if ann_s != s or ann_L != L:
                if r.random() < 0.6:
                    B.add(max(0, s - r.randint(0, 6)), "outage_correction", ref=nl.Ref(o1), core=nl.Plain(c), start=T(s),
                          dur=nl.Dur(L * 6 / 24, "d", nd=1, approx=True))
        for b, kind, j in self.events:
            if kind == "temperature":
                bb = b + r.randint(0, 1); r.random(); r.random(); dk = r.uniform(0.3, 1.2)
                B.add(bb, "temp_event", dk=nl.Plain(f"{dk:.1f} K"))
            elif kind == "earthquake":
                mag = r.uniform(4.6, 5.8); r.random(); dist = r.randint(40, 200)
                B.add(b, "quake_felt", mag=nl.Plain(f"{mag:.1f}"), dist=nl.Plain(f"{dist} km"))
            else:
                bb = b + r.randint(0, 2); r.random()
                B.add(bb, "hv_trip_cd")
        for b in self.flash_start:
            if r.random() < 0.7:
                B.add(b + r.randint(0, 3), "flasher")
        if self.leak_start is not None:
            B.add(self.leak_start + r.randint(0, 8), "leak")
        for _ in range(r.randint(2, 4)):  # noise and rumours (as in v2)
            k = mr.choice(["rumour_core", "grid_normal", "chatter"])
            b = r.randint(0, BLOCKS - 1)
            if k == "rumour_core":
                B.add(b, k, core=nl.Plain(mr.choice(["Yangjiang-5", "Taishan-3", "Yangjiang-6"])))
            else:
                B.add(b, k)
        for _ in range(mr.randint(1, 3)):  # look-alikes that must NOT trigger a calibration
            b = mr.randint(0, BLOCKS - 1); k = mr.choice(["quake_far", "temp_minor", "hv_trip_veto"])
            if k == "quake_far":
                B.add(b, k, mag=nl.Plain(f"{mr.uniform(4.6, 5.8):.1f}"), dist=nl.Plain(f"{mr.randint(40, 200)} km"))  # same ranges as felt quakes
            elif k == "temp_minor":
                B.add(b, k, dk=nl.Plain(f"{mr.uniform(0.3, 1.2):.1f} K"))  # same range as LS temperature events
            else:
                B.add(b, k)
        for _ in range(mr.randint(6, 12)):
            B.add(mr.randint(0, BLOCKS - 1), "chatter")
        fin = B.finalize(minute_of=lambda t: max(0, t) * BLOCK_H * 60)
        self.msgs = [(m["t"], m["id"], m["text"]) for m in fin]
        self.msg_kinds = {m["id"]: (m["kind"], m["slots"]) for m in fin}  # organizer-side only (never sent)

    # ---------------------------------------------------------------- truth
    def scale(self, b):
        rng = random.Random(self.seed * 5051)
        s = 1.0
        for k in range(b + 1):
            s += self.drift_rate + rng.gauss(0, 0.0003)  # v3: (v2: 0.0006)
            for eb, kind, j in self.events:
                if eb == k:
                    s += j
            for mb in self.maint_blocks:
                if mb == k:
                    s += random.Random(self.seed * 13 + mb).uniform(-0.006, 0.006)  # re-ramp after maintenance
        return s

    def flasher(self, b):
        for fs in self.flash_start:
            if fs <= b and not any(fs <= mb < b for mb in self.maint_blocks) and b < fs + 30:
                return True
        return False

    def leak(self, b):
        return self.leak_start is not None and self.leak_start <= b and not any(self.leak_start <= mb < b for mb in self.maint_blocks)

    def power(self, b):
        return sum(1 for c in CORES if b not in self.core_off[c]) / len(CORES)

    # ---------------------------------------------------------------- protocol
    def initialize(self):
        self.b = 0
        self.done = False
        self.maint_blocks = []
        self.modes = []
        self.flagged = set()
        self.calib_scale = 1.0  # scale assumed by the analysis (set at calibration)
        self.block_q = {}
        self.sent = 0
        self.last = None
        return {"problem": "osc_run", "version": "v3", "global_wallclock_seconds": WALLCLOCK, "block_hours": BLOCK_H,
                "blocks": BLOCKS, "cores": CORES, "n_capture_peak_mev": NC_PEAK,
                "scoring": {"physics_block": f"{W_PHYS} x reactor_power_fraction x q, q = 1 if |energy-scale error| < 0.2%, "
                                             "falling linearly to 0 at 1.2%; error = true scale vs the scale fixed at your last calibration",
                            "background_block_bonus": f"+{BKG_BONUS} per unflagged clean physics block with reactor power fraction <= 0.67, i.e. at least 2 of 6 cores off (max {BKG_CAP})",
                            "flasher_block_included": -FLASHER_PENALTY, "leak": "physics value x0.6 while the water leak is active",
                            "calibration_or_maintenance_block": 0, "flag_bad": "you may flag any of the last 8 blocks; flagged blocks score 0",
                            "llm_cost_points_per_1k_tokens": {"in": LLM_COST_IN, "out": LLM_COST_OUT}}}

    def snapshot(self):
        b = self.b
        new = []
        while self.sent < len(self.msgs) and self.msgs[self.sent][0] <= b:
            m, mid, text = self.msgs[self.sent]
            new.append({"id": mid, "time": block_label(max(0, m)), "text": text}); self.sent += 1
        return {"block": b, "time": block_label(b), "last_block": self.last, "new_messages": new,
                "flaggable_blocks": [x for x in range(max(0, b - 8), b) if self.modes[x] == "physics" and x not in self.flagged],
                "calibrated_scale_in_use": round(self.calib_scale, 5)}

    def step(self, action):
        if self.done:
            return
        b = self.b
        a = action if isinstance(action, dict) else {}
        mode = a.get("mode") if a.get("mode") in ("physics", "calibration", "maintenance") else "physics"
        for x in a.get("flag_bad") or []:
            if isinstance(x, int) and not isinstance(x, bool) and max(0, b - 8) <= x < b and self.modes[x] == "physics":
                self.flagged.add(x)
        rng = random.Random(self.seed * 1000003 + b)
        if mode == "maintenance":
            self.maint_blocks.append(b)
        self.modes.append(mode)
        true_s = self.scale(b)
        if mode == "calibration":
            self.calib_scale = true_s + rng.gauss(0, 0.0005)
            self.last = {"block": b, "mode": mode, "calibration_result": {"scale": round(self.calib_scale, 5),
                         "ge68_peak_mev": round(1.022 * self.calib_scale, 4)}}
        elif mode == "maintenance":
            self.last = {"block": b, "mode": mode, "report": "maintenance done; PMT HV re-ramped"}
        else:
            p = self.power(b)
            bkg = 3.0 + (15.0 if self.leak(b) else 0.0)
            lam = 60.0 * p + bkg
            n = self._poisson(rng, lam)
            fl = self.flasher(b)
            # v3: weaker flasher signature than v2 (0.10-0.35 instead of 0.12-0.6)
            anomaly = (rng.uniform(0.10, 0.35) if fl else max(0.0, rng.gauss(0.08, 0.06)) + (rng.uniform(0.15, 0.4) if rng.random() < 0.12 else 0))
            self.last = {"block": b, "mode": mode, "ibd_candidates": n, "n_capture_peak_mev": round(NC_PEAK * true_s / self.calib_scale + rng.gauss(0, NC_NOISE), 4),
                         "single_rate_hz": round(20 + (12 if self.leak(b) else 0) + rng.gauss(0, 1.5), 1),
                         "hit_pattern_anomaly": round(anomaly, 3), "muon_rate_hz": round(3.7 + rng.gauss(0, 0.05), 2)}
            err = abs(true_s / self.calib_scale - 1.0)
            q = 1.0 if err < 0.002 else max(0.0, 1.0 - (err - 0.002) / 0.010)
            self.block_q[b] = (p, q, fl, self.leak(b))
        self.b += 1
        if self.b >= BLOCKS:
            self.done = True

    @staticmethod
    def _poisson(rng, lam):
        # normal approximation is fine for lam > 30; exact for small
        if lam > 30:
            return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= L:
                return k
            k += 1

    def score_report(self, llm):
        phys, bkg_blocks, flash_inc, total_q = 0.0, 0, 0, []
        for b, (p, q, fl, lk) in self.block_q.items():
            if b in self.flagged:
                continue
            if fl:
                flash_inc += 1
                continue
            v = W_PHYS * p * q * (0.6 if lk else 1.0)
            phys += v
            total_q.append(q)
            if p <= 0.67 and q > 0.5:
                bkg_blocks += 1
        bkg = BKG_BONUS * min(BKG_CAP, bkg_blocks)
        llm_cost = LLM_COST_IN * llm.get("tokens_in", 0) / 1000 + LLM_COST_OUT * llm.get("tokens_out", 0) / 1000
        total = phys + bkg - FLASHER_PENALTY * flash_inc - llm_cost
        return {"total": round(total, 1), "physics": round(phys, 1), "background_bonus": bkg, "flasher_blocks_included": flash_inc,
                "calibrations": self.modes.count("calibration"), "maintenance": self.modes.count("maintenance"),
                "mean_quality": round(sum(total_q) / len(total_q), 3) if total_q else None, "llm_cost": round(llm_cost, 1)}


# action applied for every decision after the agent crashed or ran out of wall clock (scores 0)
IDLE_ACTION = {"mode": "maintenance"}


def make_env(seed: int) -> Env:
    return Env(seed)
