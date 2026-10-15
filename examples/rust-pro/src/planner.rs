//! Planner of the rust-pro example: a greedy, required-first scheduler. Port of `python-pro/planner.py`
//! (same steps, same constants, same tie-breaking).
//!
//! Every observe decision is built in four plain steps:
//!
//! 1. Candidates. Targets that are above the altitude limit now (and for the next few minutes) and still
//!    have something to gain. Each gets a priority:
//!    `priority = value x (sky quality now / best sky quality it can ever get) x urgency`
//!    where value is REQUIRED_VALUE for an unfinished required target (the penalty it avoids), plus the
//!    science weight still open, plus any observation-request reward. The middle factor prefers targets
//!    that are close to transit and away from the Moon; urgency grows when few nights are left for it.
//! 2. Exposure time. For each candidate the planner computes how long it must expose to reach its goal
//!    (factor 0.5 + a safety margin for a required target, factor 0.9 within 30 minutes for the others),
//!    using the public sky model times the learned sky quality. The best few are the "anchors".
//! 3. Field. The telescope is pointed so that the anchor sits on a central fibre. Every other fibre takes
//!    the neighbouring target that gains the most from the same exposure. The anchor whose field earns the
//!    most per second wins.
//! 4. Program. DARK / BRIGHT / BACKUP is chosen from the predicted sky quality of the assigned targets.
//!
//! What the planner learns from results:
//! * the factor each target has reached (only its best exposure counts),
//! * the sky quality: observed factor / predicted factor of unsaturated hits. Its recent median scales all
//!   predictions; main.rs also watches it for instrument faults.
//!
//! It uses only the catalogue, the public score configuration, bulletins and its own hits.

use serde_json::{json, Map, Value};
use std::collections::{BTreeSet, HashMap, VecDeque};

use crate::log;
use crate::skymath::{
    local_sidereal_deg, max_hour_angle_deg, normalized_airmass, parse_utc, psum, radec_to_altaz, round_to,
    shift_altaz, tangent_offsets, wrap180, FiberGrid, LunarModel, Moon, SIDEREAL_DEG_PER_SECOND,
};

// --- values --------------------------------------------------------------------------------------------
const REQUIRED_VALUE: f64 = 50.0; // planning value of finishing one required target (= the penalty it avoids)
const REQUIRED_MARGIN: f64 = 1.3; // plan required exposures for factor 0.5 x this (predictions are uncertain)
const REQUEST_MARGIN: f64 = 1.3; // same margin for observation-request targets
const DONE_FACTOR: f64 = 0.9; // an ordinary target counts as done at this factor
// --- search size ---------------------------------------------------------------------------------------
pub const N_ANCHORS: usize = 6; // anchors tried per decision (main.rs lowers this when the CPU budget is tight)
const ORDINARY_MAX_EXPOSURE: f64 = 1800.0; // longest exposure planned for an ordinary (not required) anchor (s)
const MIN_EXPOSURE: f64 = 300.0; // shortest exposure the planner proposes (s) unless the night is ending
const EXPOSURE_STEP: f64 = 150.0; // exposure times are rounded up to multiples of this
const EDGE_MARGIN_DEG: f64 = 0.02; // keep targets this far inside their fibre's glass (pointing is not perfect)
const ALT_MARGIN_DEG: f64 = 1.0; // keep targets this far above the altitude limit
// --- learning ------------------------------------------------------------------------------------------
const QUALITY_WINDOW: usize = 8; // exposures in the running sky-quality estimate
const QUALITY_FLOOR: f64 = 0.05; // never plan with a sky quality below this
// --- bulletins -----------------------------------------------------------------------------------------
const CLOSED_KINDS: [&str; 2] = ["rain", "storm"]; // over the whole sky: the site is closed
const WEATHER_KINDS: [&str; 5] = ["rain", "storm", "overcast", "haze", "cold_snap"];
const BLOCKING_KINDS: [&str; 2] = ["rocket_launch", "terrain_obstruction"];

/// The three programs; multipliers and votes are indexed in this order (also the tie-breaking order).
const PROGRAMS: [&str; 3] = ["DARK", "BRIGHT", "BACKUP"];
const BACKUP: usize = 2;

/// Azimuth of a compass direction.
fn direction_az(direction: &str) -> Option<f64> {
    let az = match direction {
        "N" => 0.0,
        "NE" => 45.0,
        "E" => 90.0,
        "SE" => 135.0,
        "S" => 180.0,
        "SW" => 225.0,
        "W" => 270.0,
        "NW" => 315.0,
        _ => return None,
    };
    Some(az)
}

fn near(az: f64, direction: &str, width: f64) -> bool {
    direction_az(direction).is_some_and(|centre| wrap180(az - centre).abs() <= width)
}

/// A JSON value as Python's str() shows it (ids may be strings or numbers).
pub fn text_of(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::String(s) => s.clone(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        other => other.to_string(),
    }
}

fn num(value: &Value, default: f64) -> f64 {
    value.as_f64().unwrap_or(default)
}

/// The catalogue's `required` column: "1" / "true" (any case) / true.
fn is_required(value: &Value) -> bool {
    matches!(text_of(value).to_lowercase().as_str(), "1" | "true")
}

/// Upper median of a list (Python `sorted(v)[len(v) // 2]`); the list must not be empty.
pub fn upper_median(values: &[f64]) -> f64 {
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    sorted[sorted.len() / 2]
}

/// One target's sky right now (computed lazily, at most once per decision).
#[derive(Clone, Copy)]
struct Sky {
    alt: f64,
    az: f64,
    model: f64, // public sky model: Moon factor / (q0 x airmass ^ exponent)
    up: f64,    // seconds until it sets below the altitude limit
    dirf: f64,  // direction factor (1 clear, 0 blocked)
}

/// The best field so far: gain per second, pointing, exposure and fibre -> target in assignment order.
struct Field {
    rate: f64,
    alt: f64,
    az: f64,
    t: f64,
    pick: Vec<(usize, usize)>,
}

/// The prediction for one target of the exposure in flight (compared with its hit afterwards).
struct Pending {
    target: usize,
    model_reach: f64, // factor the clear-sky model predicts (no quality factor)
    clean: bool,      // no weather on this target: usable for the quality estimate
}

pub struct Planner {
    lat: f64,
    lon: f64,
    min_alt: f64,
    pub nights: Vec<(f64, f64)>,
    pub slot_seconds: f64,
    grid: FiberGrid,
    pub min_exposure: f64,
    max_exposure: f64,
    f0t0: f64,
    q0: f64,
    airmass_exponent: f64,
    band_dark: f64,
    band_bright: f64,
    multipliers: [f64; 3],
    mismatch: f64,
    lunar_model: LunarModel,
    req_goal: f64,

    // catalogue
    ids: Vec<String>,
    index_of: HashMap<String, usize>,
    ra: Vec<f64>,
    dec: Vec<f64>,
    flux: Vec<f64>,
    weight: Vec<f64>,
    required: Vec<bool>,
    hmax: Vec<f64>,
    // sin(alt) = A + B cos(LST) + C sin(LST): visibility of every target without per-target trigonometry
    alt_a: Vec<f64>,
    alt_b: Vec<f64>,
    alt_c: Vec<f64>,
    sin_alt_limit: f64,
    ideal_model: Vec<f64>,                   // best sky model a target can ever get: at transit, Moon down
    cells: HashMap<i64, (Vec<f64>, Vec<usize>)>, // integer declination -> (RAs ascending, target indices)
    last_night: Vec<i64>,                    // last night on which each target is up (-1: never)

    // what we have learned
    factor: Vec<f64>,                // best completion factor reached so far (conservative)
    failed: Vec<i32>,                // assigned but no usable hit (fibre edge, blocked direction)
    quality: VecDeque<f64>,          // per-exposure median of observed / predicted
    scale: f64,                      // sky quality used for planning
    notices: BTreeSet<(String, String)>, // (event_kind, direction) in the latest bulletin
    terrain: BTreeSet<String>,       // directions with a permanent terrain obstruction
    pub log_avoid: BTreeSet<String>, // directions the staff notes say to avoid now (log_reader.rs)
    request_bonus: HashMap<usize, f64>, // target index -> request reward share
    request_threshold: HashMap<usize, f64>,
    pending: Vec<Pending>,           // the exposure in flight
    pending_program: usize,
    pub last_quality: Option<f64>,   // median observed / predicted of the last exposure (main.rs reads it)
    pub quality_night: Option<usize>, // ... the night index of that exposure
    pub quality_clean: bool,         // ... and whether it ran without all-sky weather
    pending_night: Option<usize>,
    pending_clean: bool,
    pub n_anchors: usize,
}

impl Planner {
    pub fn new(init: &Value) -> Planner {
        let site = &init["site"];
        let lat = num(&site["latitude_deg"], 0.0);
        let min_alt = num(&site["minimum_altitude_deg"], 0.0);
        let survey = &init["survey"];
        let nights: Vec<(f64, f64)> = survey["nights"]
            .as_array()
            .map_or(&[][..], Vec::as_slice)
            .iter()
            .map(|n| {
                let start = parse_utc(n["observing_start_utc"].as_str().unwrap_or(""));
                (start, parse_utc(n["observing_end_utc"].as_str().unwrap_or("")))
            })
            .collect();
        let instrument = &init["instrument"];
        let score = &init["scoring"];
        let program = &score["program"];
        let lunar = &score["lunar_model"];

        // catalogue
        let columns: Vec<String> = init["targets"]["columns"]
            .as_array()
            .map_or(Vec::new(), |c| c.iter().map(text_of).collect());
        let col = |name: &str| columns.iter().position(|c| c == name).unwrap_or(usize::MAX);
        let rows: &[Value] = init["targets"]["rows"].as_array().map_or(&[], Vec::as_slice);
        let column_f = |name: &str| -> Vec<f64> { rows.iter().map(|r| num(&r[col(name)], 0.0)).collect() };
        let ids: Vec<String> = rows.iter().map(|r| text_of(&r[col("target_id")])).collect();
        let ra = column_f("ra_deg");
        let dec = column_f("dec_deg");
        let required: Vec<bool> = rows.iter().map(|r| is_required(&r[col("required")])).collect();

        let alt_limit = min_alt + ALT_MARGIN_DEG;
        let (sl, cl) = (lat.to_radians().sin(), lat.to_radians().cos());
        let mut planner = Planner {
            lat,
            lon: num(&site["longitude_deg"], 0.0),
            min_alt,
            nights,
            slot_seconds: num(&survey["slot_seconds"], 900.0).trunc(),
            grid: FiberGrid::new(instrument),
            min_exposure: num(&instrument["exposure"]["min_duration_seconds"], 0.0).trunc(),
            max_exposure: num(&instrument["exposure"]["max_duration_seconds"], 3600.0).trunc(),
            f0t0: num(&score["flux_zero_point"], 1.0) * num(&score["exposure_zero_point_seconds"], 1.0),
            q0: num(&score["q0"], 1.0),
            airmass_exponent: num(&score["airmass_exponent"], 1.0),
            band_dark: num(&program["bands"]["DARK"], 0.0),
            band_bright: num(&program["bands"]["BRIGHT"], 0.0),
            multipliers: PROGRAMS.map(|p| num(&program["multipliers"][p], 1.0)),
            mismatch: num(&program["mismatch_multiplier"], 1.0),
            lunar_model: LunarModel {
                maximum_penalty: num(&lunar["maximum_penalty"], 0.0),
                altitude_exponent: num(&lunar["altitude_exponent"], 1.0),
                angular_decay_scale_deg: num(&lunar["angular_decay_scale_deg"], 1.0),
            },
            req_goal: num(&score["required"]["observed_factor_threshold"], 0.5),
            index_of: ids.iter().enumerate().map(|(i, id)| (id.clone(), i)).collect(),
            flux: column_f("feature_flux"),
            weight: column_f("science_weight"),
            hmax: dec.iter().map(|&d| max_hour_angle_deg(d, lat, alt_limit)).collect(),
            alt_a: dec.iter().map(|d| sl * d.to_radians().sin()).collect(),
            alt_b: dec.iter().zip(&ra).map(|(d, r)| cl * d.to_radians().cos() * r.to_radians().cos()).collect(),
            alt_c: dec.iter().zip(&ra).map(|(d, r)| cl * d.to_radians().cos() * r.to_radians().sin()).collect(),
            sin_alt_limit: alt_limit.to_radians().sin(),
            ideal_model: Vec::new(),
            cells: HashMap::new(),
            last_night: Vec::new(),
            factor: vec![0.0; ids.len()],
            failed: vec![0; ids.len()],
            quality: VecDeque::with_capacity(QUALITY_WINDOW),
            scale: 1.0,
            notices: BTreeSet::new(),
            terrain: BTreeSet::new(),
            log_avoid: BTreeSet::new(),
            request_bonus: HashMap::new(),
            request_threshold: HashMap::new(),
            pending: Vec::new(),
            pending_program: BACKUP,
            last_quality: None,
            quality_night: None,
            quality_clean: true,
            pending_night: None,
            pending_clean: true,
            n_anchors: N_ANCHORS,
            ids,
            ra,
            dec,
            required,
        };
        planner.ideal_model = planner.dec.iter().map(|&d| planner.sky_model(90.0 - (d - lat).abs(), 1.0)).collect();
        planner.build_index();
        planner.build_last_night();
        log(&format!(
            "planner: {} targets, {} required, {} nights, {} fibres",
            planner.ids.len(),
            planner.required.iter().filter(|&&r| r).count(),
            planner.nights.len(),
            planner.grid.n
        ));
        planner
    }

    // --- precomputation ------------------------------------------------------------------------------

    /// Public sky model without weather: Moon factor / (q0 x normalized airmass ^ exponent).
    fn sky_model(&self, alt: f64, lunar: f64) -> f64 {
        lunar / (self.q0 * normalized_airmass(alt.max(1.0)).powf(self.airmass_exponent))
    }

    /// Targets bucketed by integer declination and sorted by RA, for fast neighbour lookups.
    fn build_index(&mut self) {
        let mut cells: HashMap<i64, Vec<(f64, usize)>> = HashMap::new();
        for i in 0..self.ids.len() {
            cells.entry(self.dec[i].floor() as i64).or_default().push((self.ra[i], i));
        }
        self.cells = cells
            .into_iter()
            .map(|(key, mut band)| {
                band.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
                (key, band.into_iter().unzip())
            })
            .collect();
    }

    /// Targets within about `radius` degrees of (ra, dec) (a box; duplicates are harmless).
    fn neighbours(&self, ra: f64, dec: f64, radius: f64) -> Vec<usize> {
        let mut found = Vec::new();
        let width = radius / (89.0f64.min(dec.abs() + radius).to_radians().cos()).max(0.05);
        for key in (dec - radius).floor() as i64..=(dec + radius).floor() as i64 {
            let Some((ras, members)) = self.cells.get(&key) else { continue };
            for (low, high) in [(ra - width, ra + width), (ra - width + 360.0, ra + width + 360.0), (ra - width - 360.0, ra + width - 360.0)] {
                let first = ras.partition_point(|&x| x < low);
                let last = ras.partition_point(|&x| x <= high);
                found.extend_from_slice(&members[first..last.max(first)]);
            }
        }
        found
    }

    /// Last night on which each target is up at night (for urgency).
    fn build_last_night(&mut self) {
        self.last_night = vec![-1; self.ids.len()];
        for (k, &(start, end)) in self.nights.iter().enumerate() {
            let l0 = local_sidereal_deg(start, self.lon);
            let span = (end - start) * SIDEREAL_DEG_PER_SECOND;
            for i in 0..self.ids.len() {
                let h = self.hmax[i];
                if h <= 0.0 {
                    continue;
                }
                // hour angle at night start; up at some moment of the night if the window overlaps [-h, h]
                let ha = wrap180(l0 - self.ra[i]);
                if h >= 180.0 || (-h <= ha && ha <= h) || (ha < -h && ha + span >= -h) || (ha > h && ha + span - 360.0 >= -h) {
                    self.last_night[i] = k as i64;
                }
            }
        }
    }

    // --- messages ------------------------------------------------------------------------------------

    pub fn on_messages(&mut self, messages: &[Value], latest_bulletin: &Value) {
        for message in messages {
            let record = message["record_type"].as_str().unwrap_or("");
            if record == "bulletin" && message["initial"].as_bool().unwrap_or(false) {
                for notice in message["notices"].as_array().map_or(&[][..], Vec::as_slice) {
                    if notice["event_kind"] == "terrain_obstruction" {
                        self.terrain.insert(notice["direction"].as_str().unwrap_or("").to_string());
                    }
                }
            } else if record == "state_resync" {
                self.resync(message);
            }
        }
        let field = |n: &Value, key: &str| n[key].as_str().unwrap_or("").to_string();
        self.notices = latest_bulletin["notices"]
            .as_array()
            .map_or(&[][..], Vec::as_slice)
            .iter()
            .map(|n| (field(n, "event_kind"), field(n, "direction")))
            .collect();
    }

    /// Part of the recent data was lost: restart our factors from the engine's best scores.
    fn resync(&mut self, message: &Value) {
        let rows = message["best_scores"].as_array().map_or(&[][..], Vec::as_slice);
        let best: HashMap<String, f64> = rows.iter().map(|r| (text_of(&r["target_id"]), num(&r["best_score"], 0.0))).collect();
        let top = self.multipliers.iter().cloned().fold(f64::MIN, f64::max);
        for i in 0..self.ids.len() {
            let score = best.get(&self.ids[i]).copied().unwrap_or(0.0);
            self.factor[i] = if score > 0.0 { (score / (self.weight[i] * top)).min(1.0) } else { 0.0 };
        }
        self.pending.clear();
        log(&format!("state_resync: {} targets keep a score", best.len()));
    }

    /// Spread each open observation request's reward over the targets it still needs.
    pub fn on_requests(&mut self, requests: &[Value]) {
        self.request_bonus.clear();
        self.request_threshold.clear();
        for request in requests {
            let remaining = num(&request["remaining_count"], num(&request["minimum_completed"], 1.0)).trunc();
            let reward = num(&request["completion_reward"], 0.0);
            if remaining <= 0.0 || reward <= 0.0 {
                continue;
            }
            let done: Vec<String> = request["completed_target_ids"].as_array().map_or(Vec::new(), |a| a.iter().map(text_of).collect());
            let threshold = num(&request["completion_factor_threshold"], 0.5);
            for target_id in request["target_ids"].as_array().map_or(&[][..], Vec::as_slice).iter().map(text_of) {
                let Some(&i) = self.index_of.get(&target_id) else { continue };
                if done.contains(&target_id) {
                    continue;
                }
                *self.request_bonus.entry(i).or_insert(0.0) += reward / remaining;
                let t = self.request_threshold.entry(i).or_insert(0.0);
                *t = t.max(threshold);
            }
        }
    }

    pub fn site_closed(&self) -> bool {
        self.notices.iter().any(|(kind, direction)| CLOSED_KINDS.contains(&kind.as_str()) && direction == "ALL")
    }

    fn all_sky_weather(&self) -> bool {
        self.notices.iter().any(|(kind, direction)| WEATHER_KINDS.contains(&kind.as_str()) && direction == "ALL")
    }

    // --- results -------------------------------------------------------------------------------------

    /// Learn from the last observe: factors reached and the sky quality.
    pub fn on_result(&mut self, result: &Value) {
        self.last_quality = None;
        let pending = std::mem::take(&mut self.pending);
        if result["action"] != "observe" || pending.is_empty() {
            return;
        }
        let mut hits: HashMap<String, f64> = HashMap::new();
        for hit in result["hits"].as_array().map_or(&[][..], Vec::as_slice) {
            hits.insert(text_of(&hit["target_id"]), num(&hit["score"], 0.0));
        }
        let declared = self.multipliers[self.pending_program];
        let mut ratios = Vec::new();
        for pred in &pending {
            let i = pred.target;
            let score = hits.get(&self.ids[i]).copied().unwrap_or(0.0);
            if score <= 0.0 {
                self.failed[i] += 1; // missed its fibre, blocked, or closed: try it less eagerly
                continue;
            }
            // score = weight x factor x multiplier, and we do not know whether the program matched.
            // Take the larger multiplier: a conservative factor (required targets are not dropped too early).
            let factor = (score / (self.weight[i] * declared.max(self.mismatch))).min(1.0);
            self.factor[i] = self.factor[i].max(factor);
            if factor < 0.95 && pred.clean && pred.model_reach > 0.0 {
                ratios.push(factor / pred.model_reach); // observed quality relative to the clear-sky model
            }
        }
        if ratios.len() >= 3 {
            let quality = upper_median(&ratios);
            self.last_quality = Some(quality);
            self.quality_night = self.pending_night;
            self.quality_clean = self.pending_clean;
            if self.quality.len() == QUALITY_WINDOW {
                self.quality.pop_front();
            }
            self.quality.push_back(quality);
            self.scale = upper_median(self.quality.make_contiguous()).max(QUALITY_FLOOR);
        }
    }

    /// After a repaired instrument fault the old quality samples no longer apply.
    pub fn reset_quality(&mut self) {
        self.quality.clear();
        self.scale = 1.0;
    }

    // --- planning ------------------------------------------------------------------------------------

    /// (index, start, end) of the night containing `now`.
    pub fn current_night(&self, now: f64) -> Option<(usize, f64, f64)> {
        self.nights.iter().enumerate().find(|(_, &(s, e))| s <= now && now < e).map(|(k, &(s, e))| (k, s, e))
    }

    pub fn next_night_start(&self, now: f64) -> Option<f64> {
        self.nights.iter().map(|&(s, _)| s).find(|&s| s > now)
    }

    /// 1 = clear; lower for directions with an announced event; 0 = blocked.
    fn direction_factor(&self, alt: f64, az: f64) -> f64 {
        if alt < 50.0 && self.terrain.iter().any(|d| near(az, d, 60.0)) {
            return 0.0;
        }
        let mut factor: f64 = 1.0;
        for (kind, direction) in &self.notices {
            if direction == "ALL" || !near(az, direction, 67.5) {
                continue;
            }
            if BLOCKING_KINDS.contains(&kind.as_str()) && alt < 62.0 {
                return 0.0;
            }
            if WEATHER_KINDS.contains(&kind.as_str()) {
                factor = factor.min(0.3);
            }
        }
        if self.log_avoid.iter().any(|d| near(az, d, 67.5)) {
            factor = factor.min(0.3);
        }
        factor
    }

    /// What finishing target i is still worth.
    fn value(&self, i: usize) -> f64 {
        let f = self.factor[i];
        let mut v = if f < DONE_FACTOR { self.weight[i] * (1.0 - f).max(0.0) } else { 0.0 };
        if self.required[i] && f < self.req_goal {
            v += REQUIRED_VALUE;
        }
        v + self.request_bonus.get(&i).copied().unwrap_or(0.0)
    }

    /// Target i's sky now, from the per-decision cache.
    fn sky(&self, cache: &mut [Option<Sky>], i: usize, lst: f64, moon: &Moon) -> Sky {
        if let Some(sky) = cache[i] {
            return sky;
        }
        let (alt, az) = radec_to_altaz(self.ra[i], self.dec[i], lst, self.lat);
        let ha = wrap180(lst - self.ra[i]);
        let up = if self.hmax[i] < 180.0 { (self.hmax[i] - ha) / SIDEREAL_DEG_PER_SECOND } else { 1e9 };
        let model = self.sky_model(alt, moon.lunar_factor(self.ra[i], self.dec[i]));
        let sky = Sky { alt, az, model, up, dirf: self.direction_factor(alt, az) };
        cache[i] = Some(sky);
        sky
    }

    /// Completion factor an exposure of `t` seconds should give target i.
    fn reach(&self, i: usize, t: f64, model: f64, scale: f64) -> f64 {
        (self.flux[i] * t * model * scale / self.f0t0).min(1.0)
    }

    /// Planning gain of putting target i on a fibre for `t` seconds.
    fn gain(&self, i: usize, t: f64, sky: Sky, scale: f64) -> f64 {
        if sky.up < t || sky.dirf <= 0.0 {
            return 0.0;
        }
        let r = self.reach(i, t, sky.model, scale);
        let mut g = self.weight[i] * (r - self.factor[i]).max(0.0);
        if self.required[i] && self.factor[i] < self.req_goal && r >= self.req_goal * REQUIRED_MARGIN {
            g += REQUIRED_VALUE;
        }
        if let Some(&bonus) = self.request_bonus.get(&i) {
            if r >= self.request_threshold[&i] * REQUEST_MARGIN {
                g += bonus;
            }
        }
        g * sky.dirf * 0.7f64.powi(self.failed[i])
    }

    /// Return an observe action, or None when nothing worth observing is up.
    pub fn plan(&mut self, now: f64, night_end: f64, night_index: usize) -> Option<Map<String, Value>> {
        let seconds_left = night_end - now;
        if seconds_left < self.min_exposure {
            return None;
        }
        let n = self.ids.len();
        let lst = local_sidereal_deg(now, self.lon);
        let moon = Moon::new(now + 600.0, lst, self.lat, self.lunar_model);
        let scale = self.scale;
        let mut cache: Vec<Option<Sky>> = vec![None; n];

        // 1. candidates up now and still up in 10 minutes
        let lst_soon = lst + 600.0 * SIDEREAL_DEG_PER_SECOND;
        let (c0, s0) = (lst.to_radians().cos(), lst.to_radians().sin());
        let (c1, s1) = (lst_soon.to_radians().cos(), lst_soon.to_radians().sin());
        let limit = self.sin_alt_limit;
        let mut visible = vec![false; n];
        let mut ranked: Vec<(f64, usize)> = Vec::new();
        for (i, &a) in self.alt_a.iter().enumerate() {
            if a + self.alt_b[i] * c0 + self.alt_c[i] * s0 < limit || a + self.alt_b[i] * c1 + self.alt_c[i] * s1 < limit {
                continue;
            }
            visible[i] = true;
            let v = self.value(i);
            if v > 0.0 {
                ranked.push((v, i));
            }
        }
        if ranked.is_empty() {
            return None;
        }

        // 2. priority = value x (sky now / best sky ever) x urgency; only the best few are looked at exactly
        ranked.sort_by(|a, b| b.0.total_cmp(&a.0).then(b.1.cmp(&a.1)));
        let mut anchors: Vec<(f64, f64, usize)> = Vec::new(); // (priority, exposure, target)
        for &(v, i) in ranked.iter().take(40 * self.n_anchors) {
            let sky = self.sky(&mut cache, i, lst, &moon);
            if sky.dirf <= 0.0 {
                continue;
            }
            // None: cannot reach its threshold in this sky, wait for a better moment
            let Some(t) = self.exposure_for(i, sky.model, scale) else { continue };
            let t = t.min(sky.up).min(seconds_left).trunc();
            if t < self.min_exposure {
                continue;
            }
            let nights_left = (self.last_night[i] - night_index as i64 + 1).max(1) as f64;
            let priority = v * (sky.model / self.ideal_model[i]) * sky.dirf * 0.7f64.powi(self.failed[i]) * (1.0 + 1.0 / nights_left);
            anchors.push((priority, t, i));
        }
        anchors.sort_by(|a, b| b.0.total_cmp(&a.0).then(b.1.total_cmp(&a.1)).then(b.2.cmp(&a.2)));

        // 3. fill the field around each anchor; keep the field that earns the most per second
        let radius = self.grid.fov * 0.75;
        let centre_fibre = (self.grid.side / 2) * self.grid.side + self.grid.side / 2;
        let (d_north, d_east) = self.grid.fiber_center(centre_fibre);
        let mut best: Option<Field> = None;
        for &(_, t, anchor) in anchors.iter().take(self.n_anchors) {
            let a = self.sky(&mut cache, anchor, lst, &moon);
            let (c_alt, c_az) = shift_altaz(a.alt, a.az, -d_north, -d_east);
            if !(self.min_alt <= c_alt && c_alt <= 89.0) {
                continue;
            }
            // (fibre, gain, target) in first-assignment order; a better target replaces one in place
            let mut pick: Vec<(usize, f64, usize)> = Vec::new();
            for j in self.neighbours(self.ra[anchor], self.dec[anchor], radius) {
                if !visible[j] {
                    continue;
                }
                let sky = self.sky(&mut cache, j, lst, &moon);
                let Some((dn, de)) = tangent_offsets(sky.alt, sky.az, c_alt, c_az) else { continue };
                let (Some(fibre), margin) = self.grid.classify(dn, de) else { continue };
                if margin < EDGE_MARGIN_DEG {
                    continue;
                }
                let g = self.gain(j, t, sky, scale);
                if g <= 0.0 {
                    continue;
                }
                match pick.iter_mut().find(|p| p.0 == fibre) {
                    Some(slot) if g > slot.1 => *slot = (fibre, g, j),
                    Some(_) => {}
                    None => pick.push((fibre, g, j)),
                }
            }
            let total = psum(pick.iter().map(|p| p.1));
            if !pick.is_empty() && best.as_ref().is_none_or(|b| total / t > b.rate) {
                let pick = pick.iter().map(|&(f, _, j)| (f, j)).collect();
                best = Some(Field { rate: total / t, alt: c_alt, az: c_az, t, pick });
            }
        }
        let Field { alt: c_alt, az: c_az, t, pick, .. } = best?;

        // 4. program: the band most of the assigned (weighted) targets fall in
        let mut votes = [0.0f64; 3];
        for &(_, j) in &pick {
            let sky = self.sky(&mut cache, j, lst, &moon);
            votes[self.band(sky.model * scale)] += self.weight[j] * self.reach(j, t, sky.model, scale);
        }
        let all_votes = psum(votes);
        let worth = |p: usize| votes[p] * self.multipliers[p] + (all_votes - votes[p]) * self.mismatch;
        let program = (1..3).fold(0, |best, p| if worth(p) > worth(best) { p } else { best });

        // what the clear-sky model predicts (no quality factor): on_result compares the hits with it
        let clean = !self.all_sky_weather();
        let pending: Vec<Pending> = pick
            .iter()
            .map(|&(_, j)| {
                let sky = self.sky(&mut cache, j, lst, &moon);
                Pending { target: j, model_reach: self.flux[j] * t * sky.model / self.f0t0, clean: clean && sky.dirf >= 1.0 }
            })
            .collect();
        self.pending = pending;
        self.pending_program = program;
        self.pending_night = Some(night_index);
        self.pending_clean = clean;

        let mut sorted = pick;
        sorted.sort();
        let assignments: Map<String, Value> = sorted.iter().map(|&(f, j)| (f.to_string(), json!(self.ids[j]))).collect();
        let action = json!({
            "action": "observe",
            "pointing": {"alt_deg": round_to(c_alt, 4), "az_deg": round_to(c_az.rem_euclid(360.0), 4)},
            "assignments": assignments,
            "duration_seconds": t as i64,
            "program": PROGRAMS[program],
        });
        action.as_object().cloned()
    }

    /// Exposure (s) that brings target i to its goal, or None when a threshold cannot be reached now.
    /// Goal: factor 0.5 x margin for an unfinished required or request target, else DONE_FACTOR.
    fn exposure_for(&self, i: usize, model: f64, scale: f64) -> Option<f64> {
        let mut goal: Option<f64> = None;
        if self.required[i] && self.factor[i] < self.req_goal {
            goal = Some(self.req_goal * REQUIRED_MARGIN);
        }
        if let Some(&threshold) = self.request_threshold.get(&i) {
            goal = Some(goal.unwrap_or(0.0).max(threshold * REQUEST_MARGIN));
        }
        let t = goal.unwrap_or(DONE_FACTOR) * self.f0t0 / (self.flux[i] * model * scale).max(1e-9);
        if goal.is_some() && t > self.max_exposure {
            return None;
        }
        let t = (t.max(MIN_EXPOSURE) / EXPOSURE_STEP).ceil() * EXPOSURE_STEP;
        Some(t.min(if goal.is_some() { self.max_exposure } else { ORDINARY_MAX_EXPOSURE }))
    }

    fn band(&self, quality: f64) -> usize {
        if quality >= self.band_dark {
            0
        } else if quality >= self.band_bright {
            1
        } else {
            BACKUP
        }
    }
}
