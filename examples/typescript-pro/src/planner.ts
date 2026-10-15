/**
 * Planner of the typescript-pro example: a greedy, required-first scheduler (port of python-pro/planner.py).
 *
 * Every observe decision is built in four plain steps:
 *
 * 1. Candidates.  Targets that are above the altitude limit now (and for the next few minutes) and still
 *    have something to gain.  Each gets a priority:
 *        priority = value  x  (sky quality now / best sky quality it can ever get)  x  urgency
 *    where value is REQUIRED_VALUE for an unfinished required target (the penalty it avoids), plus the
 *    science weight still open, plus any observation-request reward.  The middle factor prefers targets
 *    that are close to transit and away from the Moon; urgency grows when few nights are left for it.
 * 2. Exposure time.  For each candidate the planner computes how long it must expose to reach its goal
 *    (factor 0.5 + a safety margin for a required target, factor 0.9 within 30 minutes for the others),
 *    using the public sky model times the learned sky quality.  The best few are the "anchors".
 * 3. Field.  The telescope is pointed so that the anchor sits on a central fibre.  Every other fibre takes
 *    the neighbouring target that gains the most from the same exposure.  The anchor whose field earns the
 *    most per second wins.
 * 4. Program.  DARK / BRIGHT / BACKUP is chosen from the predicted sky quality of the assigned targets.
 *
 * What the planner learns from results:
 *   - the factor each target has reached (only its best exposure counts),
 *   - the sky quality: observed factor / predicted factor of unsaturated hits.  Its recent median scales all
 *     predictions; agent.ts also watches it for instrument faults.
 *
 * It uses only the catalogue, the public score configuration, bulletins and its own hits.
 * Times are UTC instants in epoch seconds (see skymath.ts).
 */
import {
  FiberGrid,
  Instrument,
  LunarModel,
  Moon,
  SIDEREAL_DEG_PER_SECOND,
  localSiderealDeg,
  maxHourAngleDeg,
  normalizedAirmass,
  parseUtc,
  pyround,
  pysum,
  pymod,
  radecToAltaz,
  radians,
  shiftAltaz,
  tangentOffsets,
  upperMedian,
  wrap180,
} from "./skymath";

// --- values --------------------------------------------------------------------------------------------
const REQUIRED_VALUE = 50.0; // planning value of finishing one required target (= the penalty it avoids)
const REQUIRED_MARGIN = 1.3; // plan required exposures for factor 0.5 x this (predictions are uncertain)
const REQUEST_MARGIN = 1.3; // same margin for observation-request targets
const DONE_FACTOR = 0.9; // an ordinary target counts as done at this factor
// --- search size ---------------------------------------------------------------------------------------
export const N_ANCHORS = 6; // anchors tried per decision (agent.ts lowers this when the CPU budget is tight)
const ORDINARY_MAX_EXPOSURE = 1800; // longest exposure planned for an ordinary (not required) anchor (s)
const MIN_EXPOSURE = 300; // shortest exposure the planner proposes (s) unless the night is ending
const EXPOSURE_STEP = 150; // exposure times are rounded up to multiples of this
const EDGE_MARGIN_DEG = 0.02; // keep targets this far inside their fibre's glass (pointing is not perfect)
const ALT_MARGIN_DEG = 1.0; // keep targets this far above the altitude limit
// --- learning ------------------------------------------------------------------------------------------
const QUALITY_WINDOW = 8; // exposures in the running sky-quality estimate
const QUALITY_FLOOR = 0.05; // never plan with a sky quality below this
// --- bulletins -----------------------------------------------------------------------------------------
const CLOSED_KINDS = new Set(["rain", "storm"]); // over the whole sky: the site is closed
const WEATHER_KINDS = new Set(["rain", "storm", "overcast", "haze", "cold_snap"]);
const BLOCKING_KINDS = new Set(["rocket_launch", "terrain_obstruction"]);
const DIRECTION_AZ: Record<string, number> = { N: 0.0, NE: 45.0, E: 90.0, SE: 135.0, S: 180.0, SW: 225.0, W: 270.0, NW: 315.0 };
const PROGRAMS = ["DARK", "BRIGHT", "BACKUP"] as const;
type Program = (typeof PROGRAMS)[number];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = Record<string, any>;

export interface ObserveAction {
  action: "observe";
  pointing: { alt_deg: number; az_deg: number };
  assignments: Record<string, string>;
  duration_seconds: number;
  program: Program;
  reason?: string;
}

/** Is azimuth `az` within `width` degrees of compass direction `direction`? */
function near(az: number, direction: string, width = 67.5): boolean {
  const centre = DIRECTION_AZ[direction];
  return centre !== undefined && Math.abs(wrap180(az - centre)) <= width;
}

/** Bulletin notices are kept as "kind|direction" strings so a Set deduplicates them like Python tuples. */
const noticeKey = (kind: string, direction: string): string => `${kind}|${direction}`;
const splitNotice = (key: string): [string, string] => {
  const at = key.indexOf("|");
  return [key.slice(0, at), key.slice(at + 1)];
};

/** First index in sorted `values` whose value is >= x (Python's bisect_left). */
function bisectLeft(values: number[], x: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((values[mid] as number) < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** First index in sorted `values` whose value is > x (Python's bisect_right). */
function bisectRight(values: number[], x: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (x < (values[mid] as number)) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** Ascending order on number tuples, like Python's tuple comparison. */
function ascending(a: number[], b: number[]): number {
  for (let k = 0; k < a.length; k++) {
    const d = (a[k] as number) - (b[k] as number);
    if (d !== 0) return d;
  }
  return 0;
}
const descending = (a: number[], b: number[]): number => ascending(b, a);

/** What the planner predicted for one assigned target of the exposure in flight. */
interface Pending {
  modelReach: number; // factor the clear-sky model predicts (no quality factor)
  clean: boolean; // no all-sky weather and no announced event in its direction
}

/** (alt, az, sky model, seconds until it sets, direction factor) of one target at the decision time. */
type SkyInfo = [number, number, number, number, number];

export class Planner {
  // site and survey
  private readonly lat: number;
  private readonly lon: number;
  private readonly minAlt: number;
  readonly nights: [number, number][];
  readonly slotSeconds: number;
  private readonly grid: FiberGrid;
  readonly minExposure: number;
  private readonly maxExposure: number;
  // public score configuration
  private readonly f0t0: number;
  private readonly q0: number;
  private readonly airmassExponent: number;
  private readonly bands: Record<string, number>;
  private readonly multipliers: Record<Program, number>;
  private readonly mismatch: number;
  private readonly lunarModel: LunarModel;
  private readonly reqGoal: number;
  // catalogue
  private readonly ids: string[];
  private readonly indexOf = new Map<string, number>();
  private readonly ra: number[];
  private readonly dec: number[];
  private readonly flux: number[];
  private readonly weight: number[];
  private readonly required: boolean[];
  private readonly hmax: number[];
  // sin(alt) = A + B cos(LST) + C sin(LST): visibility of every target without per-target trigonometry
  private readonly altA: number[];
  private readonly altB: number[];
  private readonly altC: number[];
  private readonly sinAltLimit: number;
  private readonly idealModel: number[]; // best sky model a target can ever get: at transit, Moon down
  private readonly cells = new Map<number, [number, number][]>(); // integer dec -> [(ra, index)] sorted by ra
  private readonly cellRas = new Map<number, number[]>();
  private lastNight: number[] = [];

  // what we have learned
  private readonly factor: number[]; // best completion factor reached so far (conservative)
  private readonly failed: number[]; // assigned but no usable hit (fibre edge, blocked direction)
  private quality: number[] = []; // per-exposure median of observed / predicted (last QUALITY_WINDOW)
  private scale = 1.0; // sky quality used for planning
  private notices = new Set<string>(); // "event_kind|direction" in the latest bulletin
  private readonly terrain = new Set<string>(); // directions with a permanent terrain obstruction
  logAvoid = new Set<string>(); // directions the staff notes say to avoid now (logReader.ts)
  private requestBonus = new Map<number, number>(); // target index -> request reward share
  private requestThreshold = new Map<number, number>();
  private pending = new Map<string, Pending>(); // target id -> prediction for the exposure in flight
  private pendingProgram: Program = "BACKUP";
  private pendingNight: number | null = null;
  private pendingClean = true;
  lastQuality: number | null = null; // median observed / predicted of the last exposure (agent.ts reads it)
  qualityNight: number | null = null; // ... the night index of that exposure
  qualityClean = true; // ... and whether it ran without all-sky weather
  nAnchors = N_ANCHORS;

  constructor(init: Json, private readonly log: (text: string) => void = () => {}) {
    const site = init.site;
    this.lat = Number(site.latitude_deg);
    this.lon = Number(site.longitude_deg);
    this.minAlt = Number(site.minimum_altitude_deg);
    this.nights = (init.survey.nights as Json[]).map((n) => [parseUtc(n.observing_start_utc), parseUtc(n.observing_end_utc)]);
    this.slotSeconds = Math.trunc(Number(init.survey.slot_seconds));
    const instrument = init.instrument as Instrument;
    this.grid = new FiberGrid(instrument);
    this.minExposure = Math.trunc(Number(instrument.exposure.min_duration_seconds));
    this.maxExposure = Math.trunc(Number(instrument.exposure.max_duration_seconds));
    const score = init.scoring;
    this.f0t0 = Number(score.flux_zero_point) * Number(score.exposure_zero_point_seconds);
    this.q0 = Number(score.q0);
    this.airmassExponent = Number(score.airmass_exponent);
    this.bands = score.program.bands;
    this.multipliers = score.program.multipliers;
    this.mismatch = Number(score.program.mismatch_multiplier);
    this.lunarModel = score.lunar_model;
    this.reqGoal = Number(score.required?.observed_factor_threshold ?? 0.5);

    // catalogue
    const columns: string[] = init.targets.columns;
    const col = (name: string): number => columns.indexOf(name);
    const rows: unknown[][] = init.targets.rows;
    this.ids = rows.map((row) => String(row[col("target_id")]));
    this.ids.forEach((id, i) => this.indexOf.set(id, i));
    this.ra = rows.map((row) => Number(row[col("ra_deg")]));
    this.dec = rows.map((row) => Number(row[col("dec_deg")]));
    this.flux = rows.map((row) => Number(row[col("feature_flux")]));
    this.weight = rows.map((row) => Number(row[col("science_weight")]));
    this.required = rows.map((row) => ["1", "true"].includes(String(row[col("required")]).toLowerCase()));
    this.hmax = this.dec.map((d) => maxHourAngleDeg(d, this.lat, this.minAlt + ALT_MARGIN_DEG));
    const sl = Math.sin(radians(this.lat));
    const cl = Math.cos(radians(this.lat));
    this.altA = this.dec.map((d) => sl * Math.sin(radians(d)));
    this.altB = this.dec.map((d, i) => cl * Math.cos(radians(d)) * Math.cos(radians(this.ra[i] as number)));
    this.altC = this.dec.map((d, i) => cl * Math.cos(radians(d)) * Math.sin(radians(this.ra[i] as number)));
    this.sinAltLimit = Math.sin(radians(this.minAlt + ALT_MARGIN_DEG));
    this.idealModel = this.dec.map((d) => this.skyModel(90.0 - Math.abs(d - this.lat), 1.0));
    this.buildIndex();
    this.buildLastNight();

    this.factor = new Array<number>(rows.length).fill(0.0);
    this.failed = new Array<number>(rows.length).fill(0);
    const nRequired = this.required.filter(Boolean).length;
    log(`planner: ${rows.length} targets, ${nRequired} required, ${this.nights.length} nights, ${this.grid.n} fibres`);
  }

  // --- precomputation ------------------------------------------------------------------------------

  /** Public sky model without weather: Moon factor / (q0 x normalized airmass ^ exponent). */
  private skyModel(alt: number, lunar: number): number {
    return lunar / (this.q0 * normalizedAirmass(Math.max(alt, 1.0)) ** this.airmassExponent);
  }

  /** Targets bucketed by integer declination and sorted by RA, for fast neighbour lookups. */
  private buildIndex(): void {
    this.ids.forEach((_, i) => {
      const key = Math.floor(this.dec[i] as number);
      const band = this.cells.get(key) ?? [];
      band.push([this.ra[i] as number, i]);
      this.cells.set(key, band);
    });
    for (const [key, band] of this.cells) {
      band.sort(ascending);
      this.cellRas.set(key, band.map(([ra]) => ra));
    }
  }

  /** Indices of the targets within about `radius` degrees of (ra, dec), in a fixed order. */
  neighbours(ra: number, dec: number, radius: number): number[] {
    const found: number[] = [];
    const width = radius / Math.max(0.05, Math.cos(radians(Math.min(89.0, Math.abs(dec) + radius))));
    for (let key = Math.floor(dec - radius); key <= Math.floor(dec + radius); key++) {
      const band = this.cells.get(key);
      if (!band || band.length === 0) continue;
      const ras = this.cellRas.get(key) as number[];
      for (const [low, high] of [
        [ra - width, ra + width],
        [ra - width + 360.0, ra + width + 360.0],
        [ra - width - 360.0, ra + width - 360.0],
      ] as [number, number][]) {
        const stop = bisectRight(ras, high);
        for (let k = bisectLeft(ras, low); k < stop; k++) found.push((band[k] as [number, number])[1]);
      }
    }
    return found;
  }

  /** Last night on which each target is up at night (for urgency). */
  private buildLastNight(): void {
    this.lastNight = new Array<number>(this.ids.length).fill(-1);
    this.nights.forEach(([start, end], k) => {
      const l0 = localSiderealDeg(start, this.lon);
      const span = (end - start) * SIDEREAL_DEG_PER_SECOND;
      for (let i = 0; i < this.ids.length; i++) {
        const h = this.hmax[i] as number;
        if (h <= 0.0) continue;
        // hour angle at night start; up at some moment of the night if the window overlaps [-h, h]
        const ha = wrap180(l0 - (this.ra[i] as number));
        if (h >= 180.0 || (-h <= ha && ha <= h) || (ha < -h && ha + span >= -h) || (ha > h && ha + span - 360.0 >= -h)) {
          this.lastNight[i] = k;
        }
      }
    });
  }

  // --- messages ------------------------------------------------------------------------------------

  onMessages(messages: Json[], latestBulletin: Json | null | undefined): void {
    for (const message of messages) {
      if (message.record_type === "bulletin" && message.initial) {
        for (const notice of message.notices ?? []) {
          if (notice.event_kind === "terrain_obstruction") this.terrain.add(notice.direction ?? "");
        }
      } else if (message.record_type === "state_resync") {
        this.resync(message);
      }
    }
    const notices: Json[] = latestBulletin?.notices ?? [];
    this.notices = new Set(notices.map((n) => noticeKey(n.event_kind ?? "", n.direction ?? "")));
  }

  /** Part of the recent data was lost: restart our factors from the engine's best scores. */
  private resync(message: Json): void {
    const best = new Map<string, number>();
    for (const row of message.best_scores ?? []) best.set(row.target_id, Number(row.best_score));
    const top = Math.max(...Object.values(this.multipliers).map(Number));
    this.ids.forEach((id, i) => {
      const score = best.get(id) ?? 0.0;
      this.factor[i] = score > 0 ? Math.min(1.0, score / ((this.weight[i] as number) * top)) : 0.0;
    });
    this.pending = new Map();
    this.log(`state_resync: ${best.size} targets keep a score`);
  }

  /** Spread each open observation request's reward over the targets it still needs. */
  onRequests(requests: Json[]): void {
    this.requestBonus = new Map();
    this.requestThreshold = new Map();
    for (const request of requests) {
      const remaining = Math.trunc(Number(request.remaining_count ?? request.minimum_completed ?? 1));
      const reward = Number(request.completion_reward ?? 0.0);
      if (remaining <= 0 || reward <= 0) continue;
      const done = new Set<string>(request.completed_target_ids ?? []);
      for (const targetId of request.target_ids ?? []) {
        const i = this.indexOf.get(targetId);
        if (i === undefined || done.has(targetId)) continue;
        this.requestBonus.set(i, (this.requestBonus.get(i) ?? 0.0) + reward / remaining);
        const threshold = Number(request.completion_factor_threshold ?? 0.5);
        this.requestThreshold.set(i, Math.max(this.requestThreshold.get(i) ?? 0.0, threshold));
      }
    }
  }

  /** Rain or storm over the whole sky: nothing can be observed. */
  siteClosed(): boolean {
    return [...this.notices].some((key) => {
      const [kind, direction] = splitNotice(key);
      return CLOSED_KINDS.has(kind) && direction === "ALL";
    });
  }

  /** Any weather over the whole sky (lowers the quality without a fault). */
  allSkyWeather(): boolean {
    return [...this.notices].some((key) => {
      const [kind, direction] = splitNotice(key);
      return WEATHER_KINDS.has(kind) && direction === "ALL";
    });
  }

  // --- results -------------------------------------------------------------------------------------

  /** Learn from the last observe: factors reached and the sky quality. */
  onResult(result: Json | null | undefined): void {
    this.lastQuality = null;
    if (!result || result.action !== "observe" || this.pending.size === 0) {
      this.pending = new Map();
      return;
    }
    const hits = new Map<string, number>();
    for (const hit of result.hits ?? []) hits.set(hit.target_id, Number(hit.score));
    const declared = this.multipliers[this.pendingProgram];
    const ratios: number[] = [];
    for (const [targetId, pred] of this.pending) {
      const i = this.indexOf.get(targetId) as number;
      const score = hits.get(targetId);
      if (score === undefined || score <= 0.0) {
        this.failed[i] = (this.failed[i] as number) + 1; // missed its fibre, blocked, or closed: try it less eagerly
        continue;
      }
      // score = weight x factor x multiplier, and we do not know whether the program matched.
      // Take the larger multiplier: a conservative factor (required targets are not dropped too early).
      const factor = Math.min(1.0, score / ((this.weight[i] as number) * Math.max(declared, this.mismatch)));
      this.factor[i] = Math.max(this.factor[i] as number, factor);
      if (factor < 0.95 && pred.clean && pred.modelReach > 0) {
        ratios.push(factor / pred.modelReach); // observed quality relative to the clear-sky model
      }
    }
    if (ratios.length >= 3) {
      this.lastQuality = upperMedian(ratios);
      this.qualityNight = this.pendingNight;
      this.qualityClean = this.pendingClean;
      this.quality.push(this.lastQuality);
      if (this.quality.length > QUALITY_WINDOW) this.quality.shift();
      this.scale = Math.max(QUALITY_FLOOR, upperMedian(this.quality));
    }
    this.pending = new Map();
  }

  /** After a repaired instrument fault the old quality samples no longer apply. */
  resetQuality(): void {
    this.quality = [];
    this.scale = 1.0;
  }

  // --- planning ------------------------------------------------------------------------------------

  /** [night index, start, end] of the night containing `now`, or null in daytime. */
  currentNight(now: number): [number, number, number] | null {
    for (let k = 0; k < this.nights.length; k++) {
      const [start, end] = this.nights[k] as [number, number];
      if (start <= now && now < end) return [k, start, end];
    }
    return null;
  }

  nextNightStart(now: number): number | null {
    for (const [start] of this.nights) if (start > now) return start;
    return null;
  }

  /** 1 = clear; lower for directions with an announced event; 0 = blocked. */
  private directionFactor(alt: number, az: number): number {
    for (const direction of this.terrain) {
      if (alt < 50.0 && near(az, direction, 60.0)) return 0.0;
    }
    let factor = 1.0;
    for (const key of this.notices) {
      const [kind, direction] = splitNotice(key);
      if (direction === "ALL" || !near(az, direction)) continue;
      if (BLOCKING_KINDS.has(kind) && alt < 62.0) return 0.0;
      if (WEATHER_KINDS.has(kind)) factor = Math.min(factor, 0.3);
    }
    for (const direction of this.logAvoid) {
      if (near(az, direction)) factor = Math.min(factor, 0.3);
    }
    return factor;
  }

  /** What finishing target i is still worth. */
  private value(i: number): number {
    const f = this.factor[i] as number;
    let v = f < DONE_FACTOR ? (this.weight[i] as number) * Math.max(0.0, 1.0 - f) : 0.0;
    if (this.required[i] && f < this.reqGoal) v += REQUIRED_VALUE;
    return v + (this.requestBonus.get(i) ?? 0.0);
  }

  /** Return an observe action, or null when nothing worth observing is up. */
  plan(now: number, nightEnd: number, nightIndex: number): ObserveAction | null {
    const secondsLeft = nightEnd - now;
    if (secondsLeft < this.minExposure) return null;
    const lst = localSiderealDeg(now, this.lon);
    const moon = new Moon(now + 600, lst, this.lat, this.lunarModel);
    const scale = this.scale;

    // 1. candidates up now and still up in 10 minutes
    const lstSoon = lst + 600.0 * SIDEREAL_DEG_PER_SECOND;
    const c0 = Math.cos(radians(lst));
    const s0 = Math.sin(radians(lst));
    const c1 = Math.cos(radians(lstSoon));
    const s1 = Math.sin(radians(lstSoon));
    const limit = this.sinAltLimit;
    const visible = new Set<number>();
    const ranked: [number, number][] = []; // (value, index)
    for (let i = 0; i < this.ids.length; i++) {
      const a = this.altA[i] as number;
      const b = this.altB[i] as number;
      const c = this.altC[i] as number;
      if (a + b * c0 + c * s0 < limit || a + b * c1 + c * s1 < limit) continue;
      visible.add(i);
      const v = this.value(i);
      if (v > 0.0) ranked.push([v, i]);
    }
    if (ranked.length === 0) return null;

    const info = new Map<number, SkyInfo>();
    const sky = (i: number): SkyInfo => {
      let item = info.get(i);
      if (item === undefined) {
        const [alt, az] = radecToAltaz(this.ra[i] as number, this.dec[i] as number, lst, this.lat);
        const ha = wrap180(lst - (this.ra[i] as number));
        const hmax = this.hmax[i] as number;
        const up = hmax < 180.0 ? (hmax - ha) / SIDEREAL_DEG_PER_SECOND : 1e9;
        const model = this.skyModel(alt, moon.lunarFactor(this.ra[i] as number, this.dec[i] as number));
        item = [alt, az, model, up, this.directionFactor(alt, az)];
        info.set(i, item);
      }
      return item;
    };

    /** Completion factor an exposure of T seconds should give target i. */
    const reach = (i: number, T: number): number => Math.min(1.0, ((this.flux[i] as number) * T * sky(i)[2] * scale) / this.f0t0);

    /** Planning gain of putting target i on a fibre for T seconds. */
    const gain = (i: number, T: number): number => {
      const [, , , up, dirf] = sky(i);
      if (up < T || dirf <= 0.0) return 0.0;
      const r = reach(i, T);
      const f = this.factor[i] as number;
      let g = (this.weight[i] as number) * Math.max(0.0, r - f);
      if (this.required[i] && f < this.reqGoal && r >= this.reqGoal * REQUIRED_MARGIN) g += REQUIRED_VALUE;
      const bonus = this.requestBonus.get(i);
      if (bonus !== undefined && r >= (this.requestThreshold.get(i) as number) * REQUEST_MARGIN) g += bonus;
      return g * dirf * 0.7 ** (this.failed[i] as number);
    };

    // 2. priority = value x (sky now / best sky ever) x urgency; only the best few are looked at exactly
    ranked.sort(descending);
    const anchors: [number, number, number][] = []; // (priority, exposure, index)
    for (const [v, i] of ranked.slice(0, 40 * this.nAnchors)) {
      const [, , model, up, dirf] = sky(i);
      if (dirf <= 0.0) continue;
      const exposure = this.exposureFor(i, model, scale);
      if (exposure === null) continue; // cannot reach its threshold in this sky: wait for a better moment
      const T = Math.trunc(Math.min(exposure, up, secondsLeft));
      if (T < this.minExposure) continue;
      const nightsLeft = Math.max(1, (this.lastNight[i] as number) - nightIndex + 1);
      const priority = v * (model / (this.idealModel[i] as number)) * dirf * 0.7 ** (this.failed[i] as number) * (1.0 + 1.0 / nightsLeft);
      anchors.push([priority, T, i]);
    }
    anchors.sort(descending);

    // 3. fill the field around each anchor; keep the field that earns the most per second
    const radius = this.grid.fov * 0.75;
    const half = Math.floor(this.grid.side / 2);
    const centreFibre = half * this.grid.side + half;
    let best: { rate: number; alt: number; az: number; T: number; pick: Map<number, number> } | null = null;
    for (const [, T, anchor] of anchors.slice(0, this.nAnchors)) {
      const [aAlt, aAz] = sky(anchor);
      const [dNorth, dEast] = this.grid.fiberCenter(centreFibre);
      const [cAlt, cAz] = shiftAltaz(aAlt, aAz, -dNorth, -dEast);
      if (!(this.minAlt <= cAlt && cAlt <= 89.0)) continue;
      const pick = new Map<number, [number, number]>(); // fibre -> (gain, target index), in insertion order
      for (const j of this.neighbours(this.ra[anchor] as number, this.dec[anchor] as number, radius)) {
        if (!visible.has(j)) continue;
        const offsets = tangentOffsets(sky(j)[0], sky(j)[1], cAlt, cAz);
        if (offsets === null) continue;
        const [fibre, margin] = this.grid.classify(offsets[0], offsets[1]);
        if (fibre === null || margin < EDGE_MARGIN_DEG) continue;
        const g = gain(j, T);
        if (g > 0.0 && g > (pick.get(fibre)?.[0] ?? 0.0)) pick.set(fibre, [g, j]);
      }
      const total = pysum([...pick.values()].map(([g]) => g));
      if (pick.size > 0 && (best === null || total / T > best.rate)) {
        best = { rate: total / T, alt: cAlt, az: cAz, T, pick: new Map([...pick].map(([fibre, [, j]]) => [fibre, j])) };
      }
    }
    if (best === null) return null;
    const { alt: cAlt, az: cAz, T, pick } = best;

    // 4. program: the band most of the assigned (weighted) targets fall in
    const votes: Record<Program, number> = { DARK: 0.0, BRIGHT: 0.0, BACKUP: 0.0 };
    for (const j of pick.values()) votes[this.band(sky(j)[2] * scale)] += (this.weight[j] as number) * reach(j, T);
    const allVotes = pysum(PROGRAMS.map((p) => votes[p]));
    const programScore = (p: Program): number => votes[p] * this.multipliers[p] + (allVotes - votes[p]) * this.mismatch;
    let program: Program = PROGRAMS[0];
    for (const p of PROGRAMS) if (programScore(p) > programScore(program)) program = p; // first maximum wins

    const clean = !this.allSkyWeather();
    // what the clear-sky model predicts (no quality factor): onResult compares the hits with it
    this.pending = new Map();
    for (const j of pick.values()) {
      this.pending.set(this.ids[j] as string, {
        modelReach: ((this.flux[j] as number) * T * sky(j)[2]) / this.f0t0,
        clean: clean && sky(j)[4] >= 1.0,
      });
    }
    this.pendingProgram = program;
    this.pendingNight = nightIndex;
    this.pendingClean = clean;
    const assignments: Record<string, string> = {};
    for (const fibre of [...pick.keys()].sort((a, b) => a - b)) assignments[String(fibre)] = this.ids[pick.get(fibre) as number] as string;
    return {
      action: "observe",
      pointing: { alt_deg: pyround(cAlt, 4), az_deg: pyround(pymod(cAz, 360.0), 4) },
      assignments,
      duration_seconds: T,
      program,
    };
  }

  /** Exposure (s) that brings target i to its goal, or null when a threshold cannot be reached now.
   *  Goal: factor 0.5 x margin for an unfinished required or request target, else DONE_FACTOR. */
  private exposureFor(i: number, model: number, scale: number): number | null {
    const goals: number[] = [];
    if (this.required[i] && (this.factor[i] as number) < this.reqGoal) goals.push(this.reqGoal * REQUIRED_MARGIN);
    const threshold = this.requestThreshold.get(i);
    if (threshold !== undefined) goals.push(threshold * REQUEST_MARGIN);
    const goal = goals.length > 0 ? Math.max(...goals) : DONE_FACTOR;
    const T = (goal * this.f0t0) / Math.max((this.flux[i] as number) * model * scale, 1e-9);
    if (goals.length > 0 && T > this.maxExposure) return null;
    const rounded = Math.ceil(Math.max(MIN_EXPOSURE, T) / EXPOSURE_STEP) * EXPOSURE_STEP;
    return Math.min(rounded, goals.length > 0 ? this.maxExposure : ORDINARY_MAX_EXPOSURE);
  }

  private band(quality: number): Program {
    if (quality >= Number(this.bands.DARK)) return "DARK";
    if (quality >= Number(this.bands.BRIGHT)) return "BRIGHT";
    return "BACKUP";
  }
}
