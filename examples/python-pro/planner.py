"""Planner of the python-pro example: a greedy, required-first scheduler.

Every observe decision is built in four plain steps:

1. Candidates.  Targets that are above the altitude limit now (and for the next few minutes) and still
   have something to gain.  Each gets a priority:
       priority = value  x  (sky quality now / best sky quality it can ever get)  x  urgency
   where value is REQUIRED_VALUE for an unfinished required target (the penalty it avoids), plus the
   science weight still open, plus any observation-request reward.  The middle factor prefers targets
   that are close to transit and away from the Moon; urgency grows when few nights are left for it.
2. Exposure time.  For each candidate the planner computes how long it must expose to reach its goal
   (factor 0.5 + a safety margin for a required target, factor 0.9 within 30 minutes for the others),
   using the public sky model times the learned sky quality.  The best few are the "anchors".
3. Field.  The telescope is pointed so that the anchor sits on a central fibre.  Every other fibre takes
   the neighbouring target that gains the most from the same exposure.  The anchor whose field earns the
   most per second wins.
4. Program.  DARK / BRIGHT / BACKUP is chosen from the predicted sky quality of the assigned targets.

What the planner learns from results:
  * the factor each target has reached (only its best exposure counts),
  * the sky quality: observed factor / predicted factor of unsaturated hits.  Its recent median scales all
    predictions; agent.py also watches it for instrument faults.

It uses only the catalogue, the public score configuration, bulletins and its own hits.  Standard library only.
"""
from __future__ import annotations

import bisect
import math
from collections import deque
from datetime import datetime, timedelta

from skymath import (
    SIDEREAL_DEG_PER_SECOND,
    FiberGrid,
    Moon,
    local_sidereal_deg,
    max_hour_angle_deg,
    normalized_airmass,
    parse_utc,
    radec_to_altaz,
    shift_altaz,
    tangent_offsets,
    wrap180,
)

# --- values --------------------------------------------------------------------------------------------
REQUIRED_VALUE = 50.0        # planning value of finishing one required target (= the penalty it avoids)
REQUIRED_MARGIN = 1.3        # plan required exposures for factor 0.5 x this (predictions are uncertain)
REQUEST_MARGIN = 1.3         # same margin for observation-request targets
DONE_FACTOR = 0.9            # an ordinary target counts as done at this factor
# --- search size ---------------------------------------------------------------------------------------
N_ANCHORS = 6                # anchors tried per decision (agent.py lowers this when the CPU budget is tight)
ORDINARY_MAX_EXPOSURE = 1800 # longest exposure planned for an ordinary (not required) anchor (s)
MIN_EXPOSURE = 300           # shortest exposure the planner proposes (s) unless the night is ending
EXPOSURE_STEP = 150          # exposure times are rounded up to multiples of this
EDGE_MARGIN_DEG = 0.02       # keep targets this far inside their fibre's glass (pointing is not perfect)
ALT_MARGIN_DEG = 1.0         # keep targets this far above the altitude limit
# --- learning ------------------------------------------------------------------------------------------
QUALITY_WINDOW = 8           # exposures in the running sky-quality estimate
QUALITY_FLOOR = 0.05         # never plan with a sky quality below this
# --- bulletins -----------------------------------------------------------------------------------------
CLOSED_KINDS = {"rain", "storm"}                       # over the whole sky: the site is closed
WEATHER_KINDS = {"rain", "storm", "overcast", "haze", "cold_snap"}
BLOCKING_KINDS = {"rocket_launch", "terrain_obstruction"}
DIRECTION_AZ = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0, "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0}


def _near(az: float, direction: str, width: float = 67.5) -> bool:
    return direction in DIRECTION_AZ and abs(wrap180(az - DIRECTION_AZ[direction])) <= width


class Planner:
    def __init__(self, init: dict, log=lambda text: None):
        self.log = log
        site = init["site"]
        self.lat = float(site["latitude_deg"])
        self.lon = float(site["longitude_deg"])
        self.min_alt = float(site["minimum_altitude_deg"])
        self.nights = [(parse_utc(n["observing_start_utc"]), parse_utc(n["observing_end_utc"])) for n in init["survey"]["nights"]]
        self.slot_seconds = int(init["survey"]["slot_seconds"])
        instrument = init["instrument"]
        self.grid = FiberGrid(instrument)
        self.min_exposure = int(instrument["exposure"]["min_duration_seconds"])
        self.max_exposure = int(instrument["exposure"]["max_duration_seconds"])
        score = init["scoring"]
        self.f0t0 = float(score["flux_zero_point"]) * float(score["exposure_zero_point_seconds"])
        self.q0 = float(score["q0"])
        self.airmass_exponent = float(score["airmass_exponent"])
        self.bands = score["program"]["bands"]
        self.multipliers = score["program"]["multipliers"]
        self.mismatch = float(score["program"]["mismatch_multiplier"])
        self.lunar_model = score["lunar_model"]
        self.req_goal = float(score.get("required", {}).get("observed_factor_threshold", 0.5))

        # catalogue
        columns = init["targets"]["columns"]
        col = {name: columns.index(name) for name in columns}
        rows = init["targets"]["rows"]
        n = len(rows)
        self.ids = [row[col["target_id"]] for row in rows]
        self.index_of = {target_id: i for i, target_id in enumerate(self.ids)}
        self.ra = [float(row[col["ra_deg"]]) for row in rows]
        self.dec = [float(row[col["dec_deg"]]) for row in rows]
        self.flux = [float(row[col["feature_flux"]]) for row in rows]
        self.weight = [float(row[col["science_weight"]]) for row in rows]
        self.required = [str(row[col["required"]]).lower() in ("1", "true") for row in rows]
        self.hmax = [max_hour_angle_deg(d, self.lat, self.min_alt + ALT_MARGIN_DEG) for d in self.dec]
        # sin(alt) = A + B cos(LST) + C sin(LST): visibility of every target without per-target trigonometry
        sl, cl = math.sin(math.radians(self.lat)), math.cos(math.radians(self.lat))
        self.alt_a = [sl * math.sin(math.radians(d)) for d in self.dec]
        self.alt_b = [cl * math.cos(math.radians(d)) * math.cos(math.radians(r)) for d, r in zip(self.dec, self.ra)]
        self.alt_c = [cl * math.cos(math.radians(d)) * math.sin(math.radians(r)) for d, r in zip(self.dec, self.ra)]
        self.sin_alt_limit = math.sin(math.radians(self.min_alt + ALT_MARGIN_DEG))
        # best sky model a target can ever get: at transit, Moon down
        self.ideal_model = [self._sky_model(90.0 - abs(d - self.lat), 1.0) for d in self.dec]
        self._build_index()
        self._build_last_night()

        # what we have learned
        self.factor = [0.0] * n                  # best completion factor reached so far (conservative)
        self.failed = [0] * n                    # assigned but no usable hit (fibre edge, blocked direction)
        self.quality: deque = deque(maxlen=QUALITY_WINDOW)   # per-exposure median of observed / predicted
        self.scale = 1.0                         # sky quality used for planning
        self.notices: set = set()                # (event_kind, direction) in the latest bulletin
        self.terrain: set = set()                # directions with a permanent terrain obstruction
        self.log_avoid: set = set()              # directions the staff notes say to avoid now (log_reader.py)
        self.request_bonus: dict = {}            # target index -> request reward share
        self.request_threshold: dict = {}
        self.pending: dict = {}                  # target id -> prediction for the exposure in flight
        self.pending_program = "BACKUP"
        self.pending_duration = 0
        self.last_quality = None                 # median observed / predicted of the last exposure (agent.py reads it)
        self.quality_night = None                # ... the night index of that exposure
        self.quality_clean = True                  # ... and whether it ran without all-sky weather
        self.pending_night = None
        self.pending_clean = True
        self.n_anchors = N_ANCHORS
        log(f"planner: {n} targets, {sum(self.required)} required, {len(self.nights)} nights, {self.grid.n} fibres")

    # --- precomputation ------------------------------------------------------------------------------

    def _sky_model(self, alt: float, lunar: float) -> float:
        """Public sky model without weather: Moon factor / (q0 x normalized airmass ^ exponent)."""
        return lunar / (self.q0 * normalized_airmass(max(alt, 1.0)) ** self.airmass_exponent)

    def _build_index(self) -> None:
        """Targets bucketed by integer declination and sorted by RA, for fast neighbour lookups."""
        self.cells: dict = {}
        for i in range(len(self.ids)):
            self.cells.setdefault(int(math.floor(self.dec[i])), []).append((self.ra[i], i))
        for band in self.cells.values():
            band.sort()
        self.cell_ras = {key: [ra for ra, _ in band] for key, band in self.cells.items()}

    def neighbours(self, ra: float, dec: float, radius: float) -> list:
        found = []
        width = radius / max(0.05, math.cos(math.radians(min(89.0, abs(dec) + radius))))
        for key in range(int(math.floor(dec - radius)), int(math.floor(dec + radius)) + 1):
            band = self.cells.get(key)
            if not band:
                continue
            ras = self.cell_ras[key]
            for low, high in ((ra - width, ra + width), (ra - width + 360.0, ra + width + 360.0), (ra - width - 360.0, ra + width - 360.0)):
                for k in range(bisect.bisect_left(ras, low), bisect.bisect_right(ras, high)):
                    found.append(band[k][1])
        return found

    def _build_last_night(self) -> None:
        """Last night on which each target is up at night (for urgency)."""
        self.last_night = [-1] * len(self.ids)
        for k, (start, end) in enumerate(self.nights):
            l0 = local_sidereal_deg(start, self.lon)
            span = (end - start).total_seconds() * SIDEREAL_DEG_PER_SECOND
            for i in range(len(self.ids)):
                h = self.hmax[i]
                if h <= 0.0:
                    continue
                # hour angle at night start; up at some moment of the night if the window overlaps [-h, h]
                ha = wrap180(l0 - self.ra[i])
                if h >= 180.0 or -h <= ha <= h or (ha < -h and ha + span >= -h) or (ha > h and ha + span - 360.0 >= -h):
                    self.last_night[i] = k

    # --- messages ------------------------------------------------------------------------------------

    def on_messages(self, messages: list, latest_bulletin) -> None:
        for message in messages:
            if message.get("record_type") == "bulletin" and message.get("initial"):
                for notice in message.get("notices", []):
                    if notice.get("event_kind") == "terrain_obstruction":
                        self.terrain.add(notice.get("direction", ""))
            elif message.get("record_type") == "state_resync":
                self._resync(message)
        bulletin = latest_bulletin or {}
        self.notices = {(n.get("event_kind", ""), n.get("direction", "")) for n in bulletin.get("notices", [])}

    def _resync(self, message: dict) -> None:
        """Part of the recent data was lost: restart our factors from the engine's best scores."""
        best = {row["target_id"]: float(row["best_score"]) for row in message.get("best_scores", [])}
        top = max(self.multipliers.values())
        for i, target_id in enumerate(self.ids):
            score = best.get(target_id, 0.0)
            self.factor[i] = min(1.0, score / (self.weight[i] * top)) if score > 0 else 0.0
        self.pending = {}
        self.log(f"state_resync: {len(best)} targets keep a score")

    def on_requests(self, requests: list) -> None:
        """Spread each open observation request's reward over the targets it still needs."""
        self.request_bonus, self.request_threshold = {}, {}
        for request in requests:
            remaining = int(request.get("remaining_count", request.get("minimum_completed", 1)))
            reward = float(request.get("completion_reward", 0.0))
            if remaining <= 0 or reward <= 0:
                continue
            done = set(request.get("completed_target_ids", []))
            for target_id in request.get("target_ids", []):
                i = self.index_of.get(target_id)
                if i is None or target_id in done:
                    continue
                self.request_bonus[i] = self.request_bonus.get(i, 0.0) + reward / remaining
                self.request_threshold[i] = max(self.request_threshold.get(i, 0.0), float(request.get("completion_factor_threshold", 0.5)))

    def site_closed(self) -> bool:
        return any(kind in CLOSED_KINDS and direction == "ALL" for kind, direction in self.notices)

    def all_sky_weather(self) -> bool:
        return any(kind in WEATHER_KINDS and direction == "ALL" for kind, direction in self.notices)

    # --- results -------------------------------------------------------------------------------------

    def on_result(self, result) -> None:
        """Learn from the last observe: factors reached and the sky quality."""
        self.last_quality = None
        if not result or result.get("action") != "observe" or not self.pending:
            self.pending = {}
            return
        hits = {hit["target_id"]: float(hit["score"]) for hit in result.get("hits", [])}
        declared = self.multipliers[self.pending_program]
        ratios = []
        for target_id, pred in self.pending.items():
            i = self.index_of[target_id]
            score = hits.get(target_id)
            if score is None or score <= 0.0:
                self.failed[i] += 1          # missed its fibre, blocked, or closed: try it less eagerly
                continue
            # score = weight x factor x multiplier, and we do not know whether the program matched.
            # Take the larger multiplier: a conservative factor (required targets are not dropped too early).
            factor = min(1.0, score / (self.weight[i] * max(declared, self.mismatch)))
            self.factor[i] = max(self.factor[i], factor)
            if factor < 0.95 and pred["clean"] and pred["model_reach"] > 0:
                ratios.append(factor / pred["model_reach"])   # observed quality relative to the clear-sky model
        if len(ratios) >= 3:
            ratios.sort()
            self.last_quality = ratios[len(ratios) // 2]
            self.quality_night, self.quality_clean = self.pending_night, self.pending_clean
            self.quality.append(self.last_quality)
            values = sorted(self.quality)
            self.scale = max(QUALITY_FLOOR, values[len(values) // 2])
        self.pending = {}

    def reset_quality(self) -> None:
        """After a repaired instrument fault the old quality samples no longer apply."""
        self.quality.clear()
        self.scale = 1.0

    # --- planning ------------------------------------------------------------------------------------

    def current_night(self, now: datetime):
        for k, (start, end) in enumerate(self.nights):
            if start <= now < end:
                return k, start, end
        return None

    def next_night_start(self, now: datetime):
        for start, _ in self.nights:
            if start > now:
                return start
        return None

    def _direction_factor(self, alt: float, az: float) -> float:
        """1 = clear; lower for directions with an announced event; 0 = blocked."""
        for direction in self.terrain:
            if alt < 50.0 and _near(az, direction, 60.0):
                return 0.0
        factor = 1.0
        for kind, direction in self.notices:
            if direction == "ALL" or not _near(az, direction):
                continue
            if kind in BLOCKING_KINDS and alt < 62.0:
                return 0.0
            if kind in WEATHER_KINDS:
                factor = min(factor, 0.3)
        for direction in self.log_avoid:
            if _near(az, direction):
                factor = min(factor, 0.3)
        return factor

    def value(self, i: int) -> float:
        """What finishing target i is still worth."""
        f = self.factor[i]
        v = self.weight[i] * max(0.0, 1.0 - f) if f < DONE_FACTOR else 0.0
        if self.required[i] and f < self.req_goal:
            v += REQUIRED_VALUE
        return v + self.request_bonus.get(i, 0.0)

    def plan(self, now: datetime, night_end: datetime, night_index: int):
        """Return an observe action, or None when nothing worth observing is up."""
        seconds_left = (night_end - now).total_seconds()
        if seconds_left < self.min_exposure:
            return None
        lst = local_sidereal_deg(now, self.lon)
        moon = Moon(now + timedelta(seconds=600), lst, self.lat, self.lunar_model)
        scale = self.scale

        # 1. candidates up now and still up in 10 minutes
        lst_soon = lst + 600.0 * SIDEREAL_DEG_PER_SECOND
        c0, s0 = math.cos(math.radians(lst)), math.sin(math.radians(lst))
        c1, s1 = math.cos(math.radians(lst_soon)), math.sin(math.radians(lst_soon))
        limit = self.sin_alt_limit
        visible = set()
        ranked = []
        for i in range(len(self.ids)):
            a = self.alt_a[i]
            if a + self.alt_b[i] * c0 + self.alt_c[i] * s0 < limit or a + self.alt_b[i] * c1 + self.alt_c[i] * s1 < limit:
                continue
            visible.add(i)
            v = self.value(i)
            if v > 0.0:
                ranked.append((v, i))
        if not ranked:
            return None

        info: dict = {}

        def sky(i):
            """(alt, az, sky model, seconds until it sets, direction factor) of target i now."""
            item = info.get(i)
            if item is None:
                alt, az = radec_to_altaz(self.ra[i], self.dec[i], lst, self.lat)
                ha = wrap180(lst - self.ra[i])
                up = (self.hmax[i] - ha) / SIDEREAL_DEG_PER_SECOND if self.hmax[i] < 180.0 else 1e9
                item = info[i] = (alt, az, self._sky_model(alt, moon.lunar_factor(self.ra[i], self.dec[i])), up,
                                  self._direction_factor(alt, az))
            return item

        def reach(i, T):
            """Completion factor an exposure of T seconds should give target i."""
            return min(1.0, self.flux[i] * T * sky(i)[2] * scale / self.f0t0)

        def gain(i, T):
            """Planning gain of putting target i on a fibre for T seconds."""
            alt, az, model, up, dirf = sky(i)
            if up < T or dirf <= 0.0:
                return 0.0
            r = reach(i, T)
            g = self.weight[i] * max(0.0, r - self.factor[i])
            if self.required[i] and self.factor[i] < self.req_goal and r >= self.req_goal * REQUIRED_MARGIN:
                g += REQUIRED_VALUE
            if i in self.request_bonus and r >= self.request_threshold[i] * REQUEST_MARGIN:
                g += self.request_bonus[i]
            return g * dirf * 0.7 ** self.failed[i]

        # priority = value x (sky now / best sky ever) x urgency; only the best few are looked at exactly
        ranked.sort(reverse=True)
        anchors = []
        for v, i in ranked[: 40 * self.n_anchors]:
            alt, az, model, up, dirf = sky(i)
            if dirf <= 0.0:
                continue
            T = self._exposure_for(i, model, scale)
            if T is None:
                continue        # cannot reach its threshold in this sky: wait for a better moment
            T = int(min(T, up, seconds_left))
            if T < self.min_exposure:
                continue
            nights_left = max(1, self.last_night[i] - night_index + 1)
            priority = v * (model / self.ideal_model[i]) * dirf * 0.7 ** self.failed[i] * (1.0 + 1.0 / nights_left)
            anchors.append((priority, T, i))
        anchors.sort(reverse=True)

        # 3. fill the field around each anchor; keep the field that earns the most per second
        radius = self.grid.fov * 0.75
        centre_fibre = (self.grid.side // 2) * self.grid.side + self.grid.side // 2
        best = None
        for _, T, anchor in anchors[: self.n_anchors]:
            a_alt, a_az = sky(anchor)[:2]
            d_north, d_east = self.grid.fiber_center(centre_fibre)
            c_alt, c_az = shift_altaz(a_alt, a_az, -d_north, -d_east)
            if not self.min_alt <= c_alt <= 89.0:
                continue
            pick, total = {}, 0.0
            for j in self.neighbours(self.ra[anchor], self.dec[anchor], radius):
                if j not in visible:
                    continue
                offsets = tangent_offsets(sky(j)[0], sky(j)[1], c_alt, c_az)
                if offsets is None:
                    continue
                fibre, margin = self.grid.classify(*offsets)
                if fibre is None or margin < EDGE_MARGIN_DEG:
                    continue
                g = gain(j, T)
                if g > 0.0 and g > pick.get(fibre, (0.0, -1))[0]:
                    pick[fibre] = (g, j)
            total = sum(g for g, _ in pick.values())
            if pick and (best is None or total / T > best[0]):
                best = (total / T, c_alt, c_az, int(T), {fibre: j for fibre, (_, j) in pick.items()})
        if best is None:
            return None
        _, c_alt, c_az, T, pick = best

        # 4. program: the band most of the assigned (weighted) targets fall in
        votes = {"DARK": 0.0, "BRIGHT": 0.0, "BACKUP": 0.0}
        for j in pick.values():
            votes[self._band(sky(j)[2] * scale)] += self.weight[j] * reach(j, T)
        program = max(votes, key=lambda p: votes[p] * self.multipliers[p] + (sum(votes.values()) - votes[p]) * self.mismatch)

        clean = not self.all_sky_weather()
        # what the clear-sky model predicts (no quality factor): on_result compares the hits with it
        self.pending = {self.ids[j]: {"model_reach": self.flux[j] * T * sky(j)[2] / self.f0t0,
                                      "clean": clean and sky(j)[4] >= 1.0} for j in pick.values()}
        self.pending_program = program
        self.pending_duration = T
        self.pending_night, self.pending_clean = night_index, clean
        return {"action": "observe", "pointing": {"alt_deg": round(c_alt, 4), "az_deg": round(c_az % 360.0, 4)},
                "assignments": {str(fibre): self.ids[j] for fibre, j in sorted(pick.items())},
                "duration_seconds": T, "program": program}

    def _exposure_for(self, i: int, model: float, scale: float):
        """Exposure (s) that brings target i to its goal, or None when a threshold cannot be reached now.
        Goal: factor 0.5 x margin for an unfinished required or request target, else DONE_FACTOR."""
        goals = []
        if self.required[i] and self.factor[i] < self.req_goal:
            goals.append(self.req_goal * REQUIRED_MARGIN)
        if i in self.request_bonus:
            goals.append(self.request_threshold[i] * REQUEST_MARGIN)
        goal = max(goals) if goals else DONE_FACTOR
        T = goal * self.f0t0 / max(self.flux[i] * model * scale, 1e-9)
        if goals and T > self.max_exposure:
            return None
        T = math.ceil(max(MIN_EXPOSURE, T) / EXPOSURE_STEP) * EXPOSURE_STEP
        return min(T, self.max_exposure if goals else ORDINARY_MAX_EXPOSURE)

    def _band(self, quality: float) -> str:
        if quality >= float(self.bands["DARK"]):
            return "DARK"
        if quality >= float(self.bands["BRIGHT"]):
            return "BRIGHT"
        return "BACKUP"
