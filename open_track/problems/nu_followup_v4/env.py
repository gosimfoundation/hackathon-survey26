"""Problem 1 — 中微子多信使跟进 (neutrino multi-messenger optical follow-up). Version v4.

v4 vs v3 (pi's v3 agents imaged every position quoted in a circular and judged it by its light curve, so they
never needed to understand a circular — keyword + coordinate parsing kept all the text value): as in real
neutrino follow-up, the error regions now also contain UNRELATED fading transients (supernovae that exploded
before the alert, dwarf-nova outbursts, M-dwarf flares). In your own photometry they look exactly like the
counterpart (same brightness range, same fading, same flags). Only the classification circulars tell them apart,
and both kinds of circular look alike ("the fading transient at X ... it shows ..."): one says the spectrum is a
normal supernova / an outburst — unrelated; the other says it is NOT a normal supernova — consistent with the
neutrino. Collaborations also deny rumoured retractions ("reports that we retracted ... are wrong").
Reporting an unrelated transient is a wrong report (-400).


v3 vs v2 (pi's v2 agent parsed circulars with six regexes, and v2 leaked truth through wording: real candidates were
always "a new optical source", false ones "a candidate counterpart"): same physics and the same circular events, but
circulars are written by many people in English/Chinese/Japanese/Spanish (aohkit/nl.py), alert ids and coordinates
appear in several notations (decimal or sexagesimal, arcmin radii), true and false candidates differ only in how
confident the team sounds, and debunks refer to the earlier circular by id. Hidden seeds use different authors.

v2 vs v1 (pi round s1: high seed variance, and "seen twice at one position" was a free filter because every
contaminant was redrawn per exposure): more alerts and counterparts per episode; catalogued variable stars sit at
fixed positions in each field and flicker (they do not fade); asteroids move slowly, so a quick re-visit can
re-detect them near the same spot. Separating a fading transient from a flickering variable or a slow asteroid
needs the light curve, the motion, the flags and the circulars together.

One 1-m class telescope (1.0 x 1.0 deg field) chases neutrino alerts over three nights.
Hidden truth: which alerts are astrophysical, where each real optical counterpart sits, how fast it fades,
the per-slot cloud cover. Published: alert notices (machine-readable but later revised or retracted only in
prose), GCN-style circulars from other teams of varying credibility, a weather bulletin, moon state and your
own exposures' detections (real counterpart, asteroids, variable stars, artifacts).
"""
from __future__ import annotations

import math, os, random
from aohkit.text import hedge, num, pick, hhmm
from aohkit import nl

HERE = os.path.dirname(os.path.abspath(__file__))

SLOT_MIN = 10
NIGHTS = 3
SLOTS_PER_NIGHT = 48          # 8 h of dark time, 10-minute decisions
NIGHT_START_MIN = 20 * 60      # night k runs from day k 20:00 to day k+1 04:00 (minutes from episode start)
FOV_HALF = 0.5                 # deg
BASE_DEPTH = 21.0              # limiting magnitude in a clear dark 10-min exposure
REWARD_CORRECT = 1000.0
PENALTY_WRONG = 400.0
COVERAGE_BONUS = 150.0
SLOT_COST = 3.0
LLM_COST_IN, LLM_COST_OUT = 1.0, 4.0   # points per 1k tokens
WALLCLOCK = 900.0


def _wrap_dra(dra):
    return (dra + 180.0) % 360.0 - 180.0


def sep_deg(ra1, de1, ra2, de2):
    return math.hypot(_wrap_dra(ra1 - ra2) * math.cos(math.radians((de1 + de2) / 2)), de1 - de2)


class Env:
    def __init__(self, seed: int):
        self.seed = seed
        self.rng = random.Random(seed)
        self.trng = random.Random(seed * 7919 + 1)  # text-only randomness (never affects truth)
        self._build()

    # ------------------------------------------------------------------ world
    def _build(self):
        r = self.rng
        self.slot_minutes = [NIGHT_START_MIN + n * 1440 + k * SLOT_MIN for n in range(NIGHTS) for k in range(SLOTS_PER_NIGHT)]
        self.moon = [{"illumination": round(r.uniform(0.0, 1.0), 2), "ra": r.uniform(0, 360), "dec": r.uniform(-25, 25)}
                     for _ in range(NIGHTS)]
        # weather: smooth cloud fraction per slot with fronts; forecast = noisy per-night summary
        self.cloud = []
        for n in range(NIGHTS):
            level = r.choice([0.05, 0.1, 0.3, 0.6, 0.85])
            for k in range(SLOTS_PER_NIGHT):
                if r.random() < 0.06:
                    level = min(1.0, max(0.0, level + r.choice([-0.5, -0.3, 0.3, 0.5])))
                self.cloud.append(min(1.0, max(0.0, level + r.gauss(0, 0.08))))
        n_alerts = r.randint(6, 9)
        self.alerts = []
        for i in range(n_alerts):
            t = r.uniform(-6 * 60, (NIGHTS - 1) * 1440 + NIGHT_START_MIN + 6 * 60)  # minutes
            src = r.choice(["IceCube", "IceCube", "KM3NeT", "Baikal-GVD"])
            gold = r.random() < 0.45
            signalness = round(r.uniform(0.45, 0.85) if gold else r.uniform(0.12, 0.5), 2)
            astro = r.random() < signalness
            r90 = r.uniform(0.6, 1.2) if gold else r.uniform(1.0, 2.2)
            ra_true, de_true = r.uniform(0, 360), r.uniform(-20, 60)
            sigma = r90 / 2.15
            ra_rep = ra_true + r.gauss(0, sigma) / math.cos(math.radians(de_true))
            de_rep = de_true + r.gauss(0, sigma)
            has_cp = astro and r.random() < 0.85
            cp = None
            if has_cp:
                cp = {"ra": ra_true, "dec": de_true, "m0": r.uniform(18.0, 20.6), "fade": r.uniform(0.4, 1.4),
                      "id_tag": r.randint(100, 999)}
            revision = None
            if r.random() < 0.6:
                dt = r.uniform(90, 600)
                k = r.uniform(0.3, 0.6)
                revision = {"t": t + dt, "ra": ra_true + (ra_rep - ra_true) * k + r.gauss(0, sigma * 0.15),
                            "dec": de_true + (de_rep - de_true) * k + r.gauss(0, sigma * 0.15), "r90": r90 * r.uniform(0.45, 0.65)}
            retract = None
            if not astro and r.random() < 0.35:
                retract = t + r.uniform(120, 900)
            # visibility: each night the field is up for a contiguous window
            vis = []
            for n in range(NIGHTS):
                a = r.randint(0, 30); b = min(SLOTS_PER_NIGHT, a + r.randint(10, 34))
                vis.append((a, b))
            self.alerts.append({"id": None, "t": t, "src": src, "gold": gold, "signalness": signalness, "astro": astro,
                                "ra": ra_rep, "dec": de_rep, "r90": r90, "true": (ra_true, de_true), "cp": cp,
                                "revision": revision, "retract": retract, "vis": vis,
                                "energy": round(r.uniform(90, 400) if gold else r.uniform(60, 180))})
        self.alerts.sort(key=lambda a: a["t"])
        ir = random.Random(self.seed * 130363 + 7)   # v4: unrelated fading transients in the error regions
        for a in self.alerts:
            a["imposters"] = []
            for _ in range(1 if ir.random() < 0.6 else 0):
                rr_, ang = a["r90"] * 0.85 * math.sqrt(ir.random()), ir.uniform(0, 2 * math.pi)
                a["imposters"].append({"ra": a["ra"] + rr_ * math.cos(ang) / max(0.2, math.cos(math.radians(a["dec"]))),
                                       "dec": a["dec"] + rr_ * math.sin(ang), "m0": ir.uniform(18.0, 20.6),
                                       "fade": ir.uniform(0.4, 1.4), "what": ir.randrange(4)})
        for i, a in enumerate(self.alerts):
            a["id"] = f"NU{26}{1012 + int((a['t'] + 1440) // 1440):04d}{'ABCDEFGHIJKL'[i]}"
        self._build_circulars()

    def _build_circulars(self):
        """v3: same circulars as v2 (decided with the same random draws), but written by many people in 4 languages
        (aohkit/nl.py): alert ids and coordinates in several notations, true vs false candidates no longer worded
        differently (only how confident the team sounds differs, as in reality), debunks refer to the circular by id."""
        r = self.rng
        mr = random.Random(self.seed * 104729 + 3)
        B = nl.Board(nl.load_pool(HERE, self.seed), self.seed)
        teams = ["ZTF", "Pan-STARRS", "GOTO", "MASTER", "a small-telescope amateur network", "LCO", "KAIT"]

        def AID(a):
            i = a["id"]
            return nl.Choice({"en": [i, i, f"{i[:2]}-{i[2:8]}-{i[8:]}", f"{a['src']} alert {i[2:]}", f"{a['src']} {i[2:]}", i.lower()]})

        reasons_db = {"en": ["a known main-belt asteroid", "a cataclysmic variable in outburst, unrelated", "an image artifact"],
                      "zh": ["一颗已知的主带小行星", "一个正在爆发的激变变星，与此无关", "图像伪影"],
                      "ja": ["既知のメインベルト小惑星", "無関係な激変星のアウトバースト", "画像のアーティファクト"],
                      "es": ["un asteroide conocido del cinturón principal", "una variable cataclísmica en erupción, sin relación", "un artefacto de imagen"]}
        reasons_rt = {"en": ["the event was caused by a detector artifact", "a reprocessing shows it is consistent with background",
                             "it was a coincident atmospheric muon bundle"],
                      "zh": ["事件由探测器伪信号引起", "重新处理后与本底一致", "是一束偶然符合的大气缪子"],
                      "ja": ["検出器のアーティファクトによるもの", "再処理でバックグラウンドと一致", "偶然の大気ミューオン束"],
                      "es": ["el evento se debió a un artefacto del detector", "un reprocesado muestra que es compatible con el fondo"]}
        for a in self.alerts:
            lag = r.uniform(180, 1500)
            if a["cp"] is not None and r.random() < 0.5:
                cra, cde = a["cp"]["ra"] + r.gauss(0, 0.0005), a["cp"]["dec"] + r.gauss(0, 0.0005)
                cred = r.uniform(0.6, 0.95); team = r.choice(teams)
                B.add(a["t"] + lag, "cand_confident" if mr.random() < cred else "cand_tentative", team=nl.Plain(team), aid=AID(a),
                      coord=nl.Coord(cra, cde, 4), mag=nl.Plain(f"{a['cp']['m0'] + 0.3:.1f}"))
            elif r.random() < 0.45:
                fra = a["ra"] + r.uniform(-a["r90"], a["r90"]) * 0.6
                fde = a["dec"] + r.uniform(-a["r90"], a["r90"]) * 0.6
                cred = r.uniform(0.2, 0.7); team = r.choice(teams); mag = r.uniform(18.5, 20.5)
                c = B.add(a["t"] + lag, "cand_confident" if mr.random() < cred else "cand_tentative", team=nl.Plain(team),
                          aid=AID(a), coord=nl.Coord(fra, fde, 4), mag=nl.Plain(f"{mag:.1f}"))
                if r.random() < 0.6:
                    B.add(a["t"] + lag + r.uniform(200, 1500), "cand_debunk", team=nl.Plain(team), ref=nl.Ref(c), aid=AID(a),
                          reason=nl.Choice(reasons_db))
            if r.random() < 0.5:
                lim = r.uniform(19.0, 21.0); t0 = a["t"] + r.uniform(60, 900); team = r.choice(teams); pct = round(r.uniform(20, 80))
                B.add(t0, "upper_limit", team=nl.Plain(team), aid=AID(a), lim=nl.Plain(f"{lim:.1f} mag"),
                      pct=nl.Choice({"en": [f"{pct}%", f"{pct} per cent", f"about {pct}%"], "zh": [f"{pct}%", f"百分之{pct}"], "ja": [f"{pct}%"], "es": [f"{pct}%", f"el {pct} por ciento"]}))
        for a in self.alerts:  # prose-only revisions and retractions (the notice stream never changes)
            if a["revision"]:
                v = a["revision"]
                rr = v["r90"]
                B.add(v["t"], "revision", src=nl.Plain(a["src"]), aid=AID(a), coord=nl.Coord(v["ra"], v["dec"], 2),
                      r90=nl.Choice({"en": [f"{rr:.2f} deg", f"{rr * 60:.0f} arcmin", f"{rr:.2f}°"], "zh": [f"{rr:.2f}度", f"{rr * 60:.0f}角分"],
                                     "ja": [f"{rr:.2f}度", f"{rr * 60:.0f}分角"], "es": [f"{rr:.2f} grados", f"{rr * 60:.0f} minutos de arco"]}))
            if a["retract"]:
                B.add(a["retract"], "retraction", src=nl.Plain(a["src"]), aid=AID(a), reason=nl.Choice(reasons_rt))
        for a in self.alerts:  # look-alikes: known objects reported with coordinates; unofficial localisations
            if mr.random() < 0.35:
                kra = a["ra"] + mr.uniform(-a["r90"], a["r90"]) * 0.6
                kde = a["dec"] + mr.uniform(-a["r90"], a["r90"]) * 0.6
                B.add(a["t"] + mr.uniform(120, 1500), "cand_known", team=nl.Plain(mr.choice(teams)), aid=AID(a),
                      coord=nl.Coord(kra, kde, 4), mag=nl.Plain(f"{mr.uniform(18.5, 20.5):.1f}"))
            if mr.random() < 0.25:
                ang = mr.uniform(0, 2 * math.pi); off = a["r90"] * mr.uniform(0.6, 1.2)
                ura = a["ra"] + off * math.cos(ang) / max(0.2, math.cos(math.radians(a["dec"])))
                ude = a["dec"] + off * math.sin(ang); ur = a["r90"] * mr.uniform(0.45, 0.8)
                B.add(a["t"] + mr.uniform(90, 900), "revision_unofficial", src=nl.Plain(a["src"]), aid=AID(a), coord=nl.Coord(ura, ude, 2),
                      r90=nl.Choice({"en": [f"{ur:.2f} deg", f"{ur * 60:.0f} arcmin"], "zh": [f"{ur:.2f}度"], "ja": [f"{ur:.2f}度"], "es": [f"{ur:.2f} grados"]}))
        cr_ = random.Random(self.seed * 130363 + 9)   # v4 circulars (separate rng: v3 circular draws unchanged)
        W_UNREL = [{"en": "a dwarf-nova outburst of a cataclysmic variable", "zh": "一颗激变变星的矮新星爆发",
                    "ja": "激変星の矮新星爆発", "es": "un estallido de nova enana de una variable cataclísmica"},
                   {"en": "a fast-declining type Ibn supernova that exploded before the alert", "zh": "一颗在警报之前就已爆发、快速变暗的Ibn型超新星",
                    "ja": "警報より前に爆発した急減光のIbn型超新星", "es": "una supernova de tipo Ibn de declive rápido que explotó antes de la alerta"},
                   {"en": "a flare on a foreground M dwarf", "zh": "一颗前景M矮星的耀发", "ja": "前景のM型矮星のフレア",
                    "es": "una fulguración de una enana M en primer plano"},
                   {"en": "a normal type IIb supernova in a foreground galaxy, weeks old", "zh": "前景星系中一颗已有数周的普通IIb型超新星",
                    "ja": "前景銀河にある数週間前の普通のIIb型超新星", "es": "una supernova de tipo IIb normal en una galaxia cercana, de hace semanas"}]
        W_CONS = {"en": ["a featureless blue continuum fading fast — not a normal supernova",
                         "no supernova features at all and a decline faster than any known supernova",
                         "a rapidly fading source with a featureless spectrum, unlike a supernova or an outburst"],
                  "zh": ["无特征的蓝色连续谱，快速变暗——不是普通超新星", "完全没有超新星谱线，变暗速度比任何已知超新星都快"],
                  "ja": ["特徴のない青い連続スペクトルで急速に減光、通常の超新星ではない", "超新星の特徴が全くなく、既知のどの超新星より速く減光"],
                  "es": ["un continuo azul sin rasgos que se apaga rápido — no es una supernova normal",
                         "ninguna línea de supernova y un declive más rápido que cualquier supernova conocida"]}
        if self.seed >= nl.HIDDEN_SEED_MIN and os.environ.get("AOH_NL_FORCE_DEV_POOL") != "1":
            # hidden seeds: the classification phrases come from an organizer-only list with different wording, and
            # the two lists share their words (unrelated ones are "fast"/"blue"/"featureless", consistent ones talk
            # about supernovae), so a phrase list learned from the public dev seeds does not transfer
            import json as _json
            _w = _json.load(open(os.path.join(nl.ROOT, "_hidden", "nl", "nu_followup_v4_what.json")))
            W_UNREL = _w["unrelated"]
            W_CONS = {lang: [d[lang] for d in _w["consistent"]] for lang in ("en", "zh", "ja", "es")}
        for a in self.alerts:
            for im in a["imposters"]:
                if cr_.random() < 0.75:
                    mt = im["m0"] + im["fade"] * cr_.uniform(0.2, 0.6)
                    B.add(a["t"] + cr_.uniform(240, 1500), "cls_unrelated", team=nl.Plain(cr_.choice(teams + ["ePESSTO+", "SCAT"])),
                          aid=AID(a), coord=nl.Coord(im["ra"] + cr_.gauss(0, 0.0004), im["dec"] + cr_.gauss(0, 0.0004), 4),
                          mag=nl.Plain(f"{mt:.1f}"), what=nl.Choice({k: [v] for k, v in W_UNREL[im["what"] % len(W_UNREL)].items()}))
            if a["cp"] is not None and cr_.random() < 0.55:
                mt = a["cp"]["m0"] + a["cp"]["fade"] * cr_.uniform(0.2, 0.6)
                B.add(a["t"] + cr_.uniform(300, 1500), "cls_consistent", team=nl.Plain(cr_.choice(teams + ["ePESSTO+", "SCAT"])),
                      aid=AID(a), coord=nl.Coord(a["cp"]["ra"] + cr_.gauss(0, 0.0004), a["cp"]["dec"] + cr_.gauss(0, 0.0004), 4),
                      mag=nl.Plain(f"{mt:.1f}"), what=nl.Choice(W_CONS))
            if a["astro"] and not a["retract"] and cr_.random() < 0.3:
                B.add(a["t"] + cr_.uniform(60, 900), "retraction_denied", src=nl.Plain(a["src"]), aid=AID(a))
        for _ in range(r.randint(3, 7)):  # unrelated circulars
            B.add(r.uniform(0, NIGHTS * 1440), "astro_noise")
        for _ in range(mr.randint(4, 10)):
            B.add(mr.uniform(0, NIGHTS * 1440), "chatter")
        fin = B.finalize(minute_of=lambda t: int(t))
        self.circulars = [(m["t"], m["id"], m["text"]) for m in fin]
        self.msg_kinds = {m["id"]: (m["kind"], m["slots"]) for m in fin}  # organizer-side only (never sent)

    # ------------------------------------------------------------------ protocol
    def initialize(self):
        self.i = 0
        self.done = False
        self.own = {}          # candidate_id -> dict(truth flag hidden)
        self.cand_seq = 0
        self.reports = []      # (minute, alert_id, candidate_id)
        self.obs_log = []
        self.sent_circ = 0
        return {
            "problem": "nu_followup", "version": "v4", "global_wallclock_seconds": WALLCLOCK,
            "telescope": {"fov_deg": 2 * FOV_HALF, "slot_minutes": SLOT_MIN, "base_limiting_mag": BASE_DEPTH},
            "schedule": {"nights": NIGHTS, "slots_per_night": SLOTS_PER_NIGHT,
                         "night_start": "20:00", "night_end": "04:00"},
            "scoring": {"correct_counterpart": REWARD_CORRECT, "time_factor": "1.0 within 12 h of the alert, falling linearly to 0.4 at 72 h",
                        "wrong_report": -PENALTY_WRONG, "imaged_real_counterpart_bonus": COVERAGE_BONUS,
                        "per_exposure_cost": -SLOT_COST, "llm_cost_points_per_1k_tokens": {"in": LLM_COST_IN, "out": LLM_COST_OUT}},
        }

    def _minute(self):
        return self.slot_minutes[self.i]

    def _night_slot(self):
        return divmod(self.i, SLOTS_PER_NIGHT)

    def _depth(self, ra, dec):
        n, k = self._night_slot()
        moon = self.moon[n]
        d = sep_deg(ra, dec, moon["ra"], moon["dec"])
        moon_loss = 2.2 * moon["illumination"] * max(0.0, 1.0 - d / 90.0)
        c = self.cloud[self.i]
        cloud_loss = -2.5 * math.log10(max(0.03, 1.0 - 0.95 * c))
        return BASE_DEPTH - moon_loss - cloud_loss

    def snapshot(self):
        t = self._minute()
        n, k = self._night_slot()
        notices = [{"alert_id": a["id"], "issued": hhmm(int(a["t"])), "observatory": a["src"],
                    "stream": "GOLD" if a["gold"] else "BRONZE", "signalness": a["signalness"],
                    "energy_tev": a["energy"], "ra_deg": round(a["ra"], 2), "dec_deg": round(a["dec"], 2),
                    "r90_deg": round(a["r90"], 2),
                    "observable_tonight": a["vis"][n][0] <= k < a["vis"][n][1],
                    "visibility_tonight_slots": list(a["vis"][n])}
                   for a in self.alerts if a["t"] <= t]
        new_circ = []
        while self.sent_circ < len(self.circulars) and self.circulars[self.sent_circ][0] <= t:
            m, mid, text = self.circulars[self.sent_circ]
            new_circ.append({"id": mid, "time": hhmm(int(m)), "text": text})
            self.sent_circ += 1
        snap = {"slot_index": self.i, "time": hhmm(t), "night": n + 1, "slot_in_night": k,
                "moon": {"illumination": self.moon[n]["illumination"], "ra_deg": round(self.moon[n]["ra"], 1),
                         "dec_deg": round(self.moon[n]["dec"], 1)},
                "alerts": notices, "new_circulars": new_circ,
                "last_exposure": self.obs_log[-1] if self.obs_log and self.obs_log[-1]["slot_index"] == self.i - 1 else None}
        if k == 0:
            vals = self.cloud[n * SLOTS_PER_NIGHT:(n + 1) * SLOTS_PER_NIGHT]
            mean = sum(vals) / len(vals)
            fc = min(1, max(0, mean + random.Random(self.seed * 31 + n).gauss(0, 0.15)))
            snap["weather_bulletin"] = (f"Site weather for night {n + 1}: "
                + pick(self.trng, f"cloud cover around {num(self.trng, fc * 100, 0)}%", f"{'mostly clear' if fc < 0.2 else 'patchy cloud' if fc < 0.5 else 'heavy cloud'} expected",
                       f"forecast confidence low; cloud {fc:.1f} (fraction)") + ".")
        return snap

    def step(self, action):
        if self.done:
            return
        t = self._minute()
        a_type = action.get("type") if isinstance(action, dict) else None
        for rep in (action.get("reports") or []) if isinstance(action, dict) else []:
            if isinstance(rep, dict) and rep.get("candidate_id") in self.own and isinstance(rep.get("alert_id"), str):
                self.reports.append((t, rep["alert_id"], rep["candidate_id"]))
        rec = {"slot_index": self.i, "time": hhmm(t), "action": "wait"}
        if a_type == "observe":
            try:
                ra, dec = float(action["ra"]), float(action["dec"])
            except (KeyError, TypeError, ValueError):
                ra = dec = None
            if ra is not None and -90 <= dec <= 90:
                rec = self._expose(ra % 360.0, dec, t)
        self.obs_log.append(rec)
        self.i += 1
        if self.i >= len(self.slot_minutes):
            self.done = True

    def _expose(self, ra, dec, t):
        r = random.Random(self.seed * 1000003 + self.i)  # per-slot noise: replay-stable regardless of call order
        n, k = self._night_slot()
        depth = self._depth(ra, dec)
        cands = []
        up = any(a["t"] <= t and a["vis"][n][0] <= k < a["vis"][n][1] and sep_deg(ra, dec, a["ra"], a["dec"]) < a["r90"] + 3
                 for a in self.alerts)
        if not up:
            return {"slot_index": self.i, "time": hhmm(t), "action": "observe", "ra_deg": ra, "dec_deg": dec,
                    "status": "field below horizon or not schedulable", "limiting_mag": None, "detections": []}
        for a in self.alerts:
            cp = a["cp"]
            if cp is None or a["t"] > t:
                continue
            if abs(_wrap_dra(cp["ra"] - ra)) * math.cos(math.radians(dec)) <= FOV_HALF and abs(cp["dec"] - dec) <= FOV_HALF:
                mag = cp["m0"] + cp["fade"] * (t - a["t"]) / 1440.0
                if mag + r.gauss(0, 0.25) < depth:
                    cands.append(("REAL", a["id"], cp["ra"], cp["dec"], mag))
                    cp["imaged"] = True
        for a in self.alerts:  # v4: unrelated fading transients (exploded before the alert; look like the counterpart)
            if a["t"] > t:
                continue
            for im in a["imposters"]:
                if abs(_wrap_dra(im["ra"] - ra)) * math.cos(math.radians(dec)) <= FOV_HALF and abs(im["dec"] - dec) <= FOV_HALF:
                    mag = im["m0"] + im["fade"] * (t - a["t"]) / 1440.0
                    if mag + r.gauss(0, 0.25) < depth:
                        cands.append(("IMPOSTER", None, im["ra"], im["dec"], mag))
        # fixed variable stars (field-locked, flicker), slow asteroids (move ~0.5-3 arcsec/min), fresh artifacts
        for (vra, vde, vmag, vamp, vph) in self._variables_near(ra, dec):
            if abs(_wrap_dra(vra - ra)) * math.cos(math.radians(dec)) <= FOV_HALF and abs(vde - dec) <= FOV_HALF:
                m = vmag + vamp * math.sin(t / 97.0 + vph)
                if m + r.gauss(0, 0.2) < depth:
                    cands.append(("VARIABLE", None, vra, vde, m))
        for (ara, ade, vra_, vde_, amag) in self._asteroids_near(ra, dec, n):
            pra, pde = ara + vra_ * (t % 1440), ade + vde_ * (t % 1440)
            if abs(_wrap_dra(pra - ra)) * math.cos(math.radians(dec)) <= FOV_HALF and abs(pde - dec) <= FOV_HALF and amag + r.gauss(0, 0.2) < depth:
                cands.append(("ASTEROID", None, pra, pde, amag))
        for _ in range(r.choice([0, 0, 1, 1, 2])):
            cands.append(("ARTIFACT", None, ra + r.uniform(-FOV_HALF, FOV_HALF) / math.cos(math.radians(dec)),
                          dec + r.uniform(-FOV_HALF, FOV_HALF), r.uniform(depth - 2.0, depth - 0.1)))
        out = []
        for kind, aid, cra, cde, mag in cands:
            self.cand_seq += 1
            cid = f"C{self.cand_seq:05d}"
            flags = []
            if kind == "VARIABLE" and r.random() < 0.8:
                flags.append("matches a catalogued variable star")
            if kind == "ARTIFACT" and r.random() < 0.7:
                flags.append(r.choice(["elongated PSF", "near saturated star", "single-pixel spike"]))
            if kind == "ASTEROID" and r.random() < 0.3:
                flags.append("slight trail")
            if kind in ("REAL", "IMPOSTER") and r.random() < 0.1:
                flags.append("near saturated star")  # realism: the real one is not always clean
            self.own[cid] = {"kind": kind, "alert": aid, "ra": cra, "dec": cde}
            out.append({"candidate_id": cid, "ra_deg": round(cra + r.gauss(0, 0.0003), 5), "dec_deg": round(cde + r.gauss(0, 0.0003), 5),
                        "mag": round(mag + r.gauss(0, 0.08), 2), "flags": flags})
        return {"slot_index": self.i, "time": hhmm(t), "action": "observe", "ra_deg": round(ra, 4), "dec_deg": round(dec, 4),
                "status": "ok", "limiting_mag": round(depth + r.gauss(0, 0.1), 2), "detections": out}

    def _cell(self, ra, dec):
        return (int(math.floor(ra / 2.0)), int(math.floor((dec + 90) / 2.0)))

    def _variables_near(self, ra, dec):
        out = []
        ci, cj = self._cell(ra, dec)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                rr = random.Random(((self.seed * 1000003 + 11) * 7919 + (ci + di) * 4099 + (cj + dj)) & 0xFFFFFFFFFFFF)
                for _ in range(rr.randint(1, 4)):
                    out.append(((ci + di) * 2.0 + rr.uniform(0, 2), (cj + dj) * 2.0 - 90 + rr.uniform(0, 2),
                                rr.uniform(17.5, 20.5), rr.uniform(0.1, 0.8), rr.uniform(0, 6.28)))
        return out

    def _asteroids_near(self, ra, dec, night):
        out = []
        ci, cj = self._cell(ra, dec)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                rr = random.Random(((self.seed * 1000003 + 29 + night) * 7919 + (ci + di) * 4099 + (cj + dj)) & 0xFFFFFFFFFFFF)
                for _ in range(rr.choice([0, 1, 1, 2])):
                    sp = rr.uniform(0.5, 3.0) / 3600.0  # deg per minute
                    ang = rr.uniform(0, 6.28)
                    out.append(((ci + di) * 2.0 + rr.uniform(0, 2), (cj + dj) * 2.0 - 90 + rr.uniform(0, 2),
                                sp * math.cos(ang), sp * math.sin(ang), rr.uniform(18.0, 20.8)))
        return out

    def score_report(self, llm):
        by_id = {a["id"]: a for a in self.alerts}
        correct, wrong, credited = 0.0, 0, set()
        detail = []
        # a report is correct if the candidate is the real counterpart of that alert, or another detection of the
        # same real source (repeat visits produce new candidate ids for the same object)
        for t, aid, cid in self.reports:
            c = self.own[cid]
            a = by_id.get(aid)
            ok = a is not None and a["cp"] is not None and sep_deg(c["ra"], c["dec"], a["cp"]["ra"], a["cp"]["dec"]) < 2 / 3600
            if ok and aid not in credited:
                hours = (t - a["t"]) / 60.0
                f = 1.0 if hours <= 12 else max(0.4, 1.0 - 0.6 * (hours - 12) / 60.0)
                correct += REWARD_CORRECT * f; credited.add(aid)
                detail.append({"alert": aid, "candidate": cid, "result": "correct", "time_factor": round(f, 3)})
            elif not ok:
                if (aid, cid) in {(d["alert"], d["candidate"]) for d in detail if d["result"] == "wrong"}:
                    continue
                wrong += 1
                detail.append({"alert": aid, "candidate": cid, "result": "wrong"})
        imaged = sum(1 for a in self.alerts if a["cp"] and a["cp"].get("imaged"))
        exposures = sum(1 for o in self.obs_log if o.get("action") == "observe" and o.get("status") == "ok")
        llm_cost = LLM_COST_IN * llm.get("tokens_in", 0) / 1000 + LLM_COST_OUT * llm.get("tokens_out", 0) / 1000
        total = correct - PENALTY_WRONG * wrong + COVERAGE_BONUS * imaged - SLOT_COST * exposures - llm_cost
        return {"total": round(total, 1), "correct_points": round(correct, 1), "wrong_reports": wrong,
                "real_counterparts": sum(1 for a in self.alerts if a["cp"]), "imaged_real": imaged,
                "exposures": exposures, "llm_cost": round(llm_cost, 1), "reports": detail,
                "max_possible": REWARD_CORRECT * sum(1 for a in self.alerts if a["cp"]) + COVERAGE_BONUS * sum(1 for a in self.alerts if a["cp"])}


# action applied for every decision after the agent crashed or ran out of wall clock (scores 0)
IDLE_ACTION = {"type": "wait"}


def make_env(seed: int) -> Env:
    return Env(seed)
