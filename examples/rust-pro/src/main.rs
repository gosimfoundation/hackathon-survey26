//! rust-pro: the Rust port of the readable rule-based python-pro example agent
//! (participant-agent-protocol-v4). Same strategy and constants as `../python-pro`; each module here mirrors
//! one python-pro module.
//!
//! One JSON object per line on stdin, one per line on stdout, logs on stderr.
//!
//! Per decision request:
//!   1. learn from the last result (planner.on_result) and from new bulletins / observation requests;
//!   2. daytime or rain/storm over the whole sky: wait;
//!   3. instrument-fault rule (FaultWatch below): report when the observed quality collapses;
//!   4. otherwise ask the planner (planner.rs) for a greedy, required-first observe.
//!
//! Optional model stage (log_reader.rs): with an API key, the free-text staff notes that some cards attach to
//! observation requests are read once each by the model; announced closures become waits, bad sectors are
//! down-weighted, and announced instrument problems become reports. Without a key, or when the platform sets
//! OBSERVER_MODEL_DISABLED=1 (an evaluation without a model), the agent runs on its rules alone.

mod llm_client;
mod log_reader;
mod planner;
mod skymath;

use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::io::{BufRead, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};

use llm_client::{api_key, load_dotenv, model_disabled, LlmClient};
use log_reader::LogReader;
use planner::{upper_median, Planner, N_ANCHORS};
use skymath::{format_utc, parse_utc};

const PROTOCOL: &str = "participant-agent-protocol-v4";
const NOTE_WAIT_MAX: f64 = 120.0; // longest real-time wait for the model's reading of a new staff note (s)

pub fn log(text: &str) {
    let mut err = std::io::stderr().lock();
    let _ = writeln!(err, "{text}");
    let _ = err.flush();
}

/// User + system CPU time of this process (all threads), like Python's `time.process_time()`.
#[cfg(unix)]
fn process_time() -> f64 {
    // SAFETY: getrusage only writes into the zeroed struct we hand it.
    let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
    if unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut usage) } != 0 {
        return 0.0;
    }
    let seconds = |t: libc::timeval| t.tv_sec as f64 + t.tv_usec as f64 / 1e6;
    seconds(usage.ru_utime) + seconds(usage.ru_stime)
}

#[cfg(not(unix))]
fn process_time() -> f64 {
    0.0
}

fn wait_for(seconds: f64, reason: &str) -> Map<String, Value> {
    action(json!({"action": "wait", "duration_seconds": seconds as i64, "reason": reason}))
}

fn wait_until(moment: f64, reason: &str) -> Map<String, Value> {
    action(json!({"action": "wait", "until_utc": format_utc(moment), "reason": reason}))
}

fn action(value: Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}

/// A simple, conservative instrument-fault rule.
///
/// The planner gives, after every exposure, the median of observed / predicted factor over its hits
/// ("quality"). A fault multiplies the instrument efficiency by some factor until it is reported; weather
/// and earthquakes lower the quality too, and a report repairs neither. Weather changes from night to
/// night, a fault stays. So the rule compares the quality with the usual level since the last repair
/// (90th percentile of exposures without all-sky weather: a clear night with a healthy instrument) and
/// reports on
///
/// * a collapse: the last COLLAPSE_RUN exposures all below COLLAPSE_LEVEL x usual, or
/// * a lasting drop: the median quality of each of the last two observed nights (at least NIGHT_MIN
///   exposures each, no all-sky weather) below DROP_LEVEL x usual.
///
/// Only exposures after the last report count as evidence, so one episode is never reported twice.
/// A wrong report is free for the first `false_report_free_allowance` times after each correct one and
/// costs points afterwards; without free reports left the rule waits PAID_SPACING_HOURS between reports
/// (a fault lasts until it is reported, so a late report still pays).
struct FaultWatch {
    free_allowance: i64,
    history: Vec<Exposure>, // since the last repair
    false_since_correct: i64,
    last_report: f64, // hours since the survey start
    reports: u32,
    correct: u32,
}

struct Exposure {
    hours: f64,
    night: usize,
    quality: f64,
    clean: bool, // no all-sky weather
}

impl FaultWatch {
    const COLLAPSE_LEVEL: f64 = 0.1;
    const COLLAPSE_RUN: usize = 2;
    const DROP_LEVEL: f64 = 0.55;
    const NIGHT_MIN: usize = 4;
    const PAID_SPACING_HOURS: f64 = 120.0;
    const MIN_HISTORY: usize = 8;

    fn new(free_allowance: i64) -> FaultWatch {
        FaultWatch { free_allowance, history: Vec::new(), false_since_correct: 0, last_report: -1e9, reports: 0, correct: 0 }
    }

    fn add(&mut self, hours: f64, night: Option<usize>, quality: Option<f64>, clean: bool) {
        if let (Some(quality), Some(night)) = (quality, night) {
            self.history.push(Exposure { hours, night, quality, clean });
        }
    }

    /// The usual quality: 90th percentile of the clean exposures since the last repair.
    fn usual(&self) -> Option<f64> {
        let recent = &self.history[self.history.len().saturating_sub(400)..];
        let mut values: Vec<f64> = recent.iter().filter(|e| e.clean).map(|e| e.quality).collect();
        values.sort_by(f64::total_cmp);
        (values.len() >= Self::MIN_HISTORY).then(|| values[(9 * values.len()) / 10])
    }

    /// Why to report now, or None.
    fn should_report(&self, hours: f64) -> Option<String> {
        let usual = self.usual()?;
        if self.false_since_correct >= self.free_allowance && hours - self.last_report < Self::PAID_SPACING_HOURS {
            return None;
        }
        // evidence since the last report
        let fresh: Vec<&Exposure> = self.history.iter().filter(|e| e.hours > self.last_report).collect();
        let last: Vec<f64> = fresh[fresh.len().saturating_sub(Self::COLLAPSE_RUN)..].iter().map(|e| e.quality).collect();
        if last.len() == Self::COLLAPSE_RUN && last.iter().all(|&q| q < Self::COLLAPSE_LEVEL * usual) {
            return Some(format!("quality collapsed to {:.2} of usual", last[last.len() - 1] / usual));
        }
        let mut nights: BTreeMap<usize, Vec<f64>> = BTreeMap::new();
        for e in fresh.iter().filter(|e| e.clean) {
            nights.entry(e.night).or_default().push(e.quality);
        }
        let recent: Vec<f64> = nights
            .values()
            .skip(nights.len().saturating_sub(2))
            .filter(|v| v.len() >= Self::NIGHT_MIN)
            .map(|v| upper_median(v))
            .collect();
        if recent.len() == 2 && recent.iter().all(|&q| q < Self::DROP_LEVEL * usual) {
            return Some(format!(
                "quality at {:.2} and {:.2} of usual on two nights",
                recent[0] / usual,
                recent[1] / usual
            ));
        }
        None
    }

    fn reported(&mut self, hours: f64) {
        self.last_report = hours;
        self.reports += 1;
    }

    fn on_result(&mut self, correct: bool) {
        if correct {
            self.correct += 1;
            self.false_since_correct = 0;
            self.history.clear(); // repaired: the usual level is measured afresh
        } else {
            self.false_since_correct += 1;
        }
    }
}

struct ObserverAgent {
    planner: Planner,
    start: f64,
    faults: FaultWatch,
    reader: Option<LogReader>,
    correct_report_at: Option<f64>,
    observes: u32,
    cpu_per_decision: f64,
}

impl ObserverAgent {
    fn new(init: &Value, use_model: bool) -> ObserverAgent {
        let reader = use_model.then(|| {
            let client = LlmClient::from_env();
            log(&format!("rust-pro: model {} reads staff notes", client.model));
            LogReader::new(client, init["site"]["utc_offset_hours"].as_f64().unwrap_or(0.0))
        });
        ObserverAgent {
            planner: Planner::new(init),
            start: parse_utc(init["survey"]["start_utc"].as_str().unwrap_or("")),
            faults: FaultWatch::new(init["scoring"]["reporting"]["false_report_free_allowance"].as_f64().unwrap_or(0.0) as i64),
            reader,
            correct_report_at: None,
            observes: 0,
            cpu_per_decision: 0.0,
        }
    }

    // --- decision loop ---------------------------------------------------------------------------------

    fn respond(&mut self, payload: &Value) -> Map<String, Value> {
        let cpu_started = process_time();
        let action = self.decide(payload);
        let cost = process_time() - cpu_started;
        self.cpu_per_decision = if self.cpu_per_decision == 0.0 { cost } else { 0.95 * self.cpu_per_decision + 0.05 * cost };
        action
    }

    fn decide(&mut self, payload: &Value) -> Map<String, Value> {
        let now = parse_utc(payload["now_utc"].as_str().unwrap_or(""));
        let hours = (now - self.start) / 3600.0;
        let last = &payload["last_result"];
        if last["action"] == "report" {
            self.on_report_result(last, now);
        }
        let list = |key: &str| payload[key].as_array().map_or(&[][..], Vec::as_slice);
        self.planner.on_messages(list("new_messages"), &payload["latest_bulletin"]);
        self.planner.on_requests(list("active_requests"));
        self.planner.on_result(last);
        let p = &self.planner;
        self.faults.add(hours, p.quality_night, p.last_quality, p.quality_clean);
        self.pace(payload, now);

        let Some((night_index, night_start, night_end)) = self.planner.current_night(now) else {
            return match self.planner.next_night_start(now) {
                Some(start) => wait_until(start, "daytime"),
                None => action(json!({"action": "finish", "reason": "no observing night left"})),
            };
        };

        if let Some(note_action) = self.read_notes(payload, now, night_end) {
            return note_action;
        }
        if night_end - now < self.planner.min_exposure {
            return match self.planner.next_night_start(now) {
                Some(start) => wait_until(start, "night ending"),
                None => action(json!({"action": "finish", "reason": "survey over"})),
            };
        }
        if self.planner.site_closed() {
            return wait_for(self.to_next_slot(now, night_start), "rain/storm over the whole sky");
        }

        if let Some(why) = self.faults.should_report(hours) {
            self.faults.reported(hours);
            log(&format!("rust-pro: report at {} ({why})", payload["now_utc"].as_str().unwrap_or("")));
            return action(json!({"action": "report", "reason": why}));
        }

        let Some(mut observe) = self.planner.plan(now, night_end, night_index) else {
            return wait_for(self.to_next_slot(now, night_start), "nothing useful is up");
        };
        self.observes += 1;
        let fibres = observe["assignments"].as_object().map_or(0, Map::len);
        let reason = format!("{fibres} fibres, {} s, {}", observe["duration_seconds"], observe["program"].as_str().unwrap_or(""));
        observe.insert("reason".into(), json!(reason));
        observe
    }

    /// Seconds to the next slot boundary of the night (1 min to 1 h).
    fn to_next_slot(&self, now: f64, night_start: f64) -> f64 {
        let slot = self.planner.slot_seconds;
        (slot - (now - night_start).rem_euclid(slot)).clamp(60.0, 3600.0)
    }

    fn on_report_result(&mut self, result: &Value, now: f64) {
        let correct = result["correct"].as_bool().unwrap_or(false);
        self.faults.on_result(correct);
        if correct {
            self.correct_report_at = Some(now);
            self.planner.reset_quality();
        }
        let verdict = if correct { "correct, fault repaired" } else { "wrong" };
        log(&format!("rust-pro: report {verdict} (delta {})", result["score_delta"]));
    }

    // --- pace ------------------------------------------------------------------------------------------

    /// Keep the planner cheap enough for the CPU budget: fewer anchors when time runs short.
    fn pace(&mut self, payload: &Value, now: f64) {
        let wall = &payload["wallclock"];
        let cpu_left = wall["remaining_real_cpu_seconds"].as_f64().or(wall["remaining_seconds"].as_f64()).unwrap_or(1e9);
        let night_left: f64 = self.planner.nights.iter().filter(|&&(_, e)| e > now).map(|&(s, e)| (e - s.max(now)).max(0.0)).sum();
        let budget = 0.6 * cpu_left / (night_left / 900.0).max(1.0); // about one decision per 15 night minutes
        let planner = &mut self.planner;
        if self.cpu_per_decision > budget {
            planner.n_anchors = planner.n_anchors.saturating_sub(1).max(1);
        } else if self.cpu_per_decision < 0.5 * budget && planner.n_anchors < N_ANCHORS {
            planner.n_anchors += 1;
        }
    }

    // --- optional: staff notes read by the model (log_reader.rs) -----------------------------------------

    fn read_notes(&mut self, payload: &Value, now: f64, night_end: f64) -> Option<Map<String, Value>> {
        let reader = self.reader.as_mut()?;
        let mut requests: Vec<&Value> = payload["active_requests"].as_array().map_or(Vec::new(), |a| a.iter().collect());
        if let Some(messages) = payload["new_messages"].as_array() {
            requests.extend(messages.iter().filter(|m| m["record_type"] == "observation_request"));
        }
        let wall_left = payload["wallclock"]["wall_remaining_seconds"].as_f64().unwrap_or(1e9);
        if reader.feed(&requests, now, wall_left) > 0 {
            reader.wait(NOTE_WAIT_MAX.min(0.02 * wall_left)); // waiting costs real time only, no CPU budget
        }
        reader.collect();
        self.planner.log_avoid = reader.avoid_now(now);
        if let Some(since) = reader.report_due(now) {
            if self.correct_report_at.is_none_or(|at| at < since) {
                self.faults.reported((now - self.start) / 3600.0);
                let from = format_utc(since)[..16].replace('T', " ");
                log(&format!(
                    "rust-pro: report at {} (staff note: instrument problem from {from})",
                    payload["now_utc"].as_str().unwrap_or("")
                ));
                return Some(action(json!({"action": "report", "reason": "staff note: instrument problem"})));
            }
        }
        let end = reader.closed(now)?;
        Some(wait_for((end - now).min(night_end - now).clamp(60.0, 3600.0), "staff note: site closed"))
    }
}

/// Model only with a key, and never when the platform runs this evaluation without a model.
fn use_model() -> bool {
    !model_disabled() && !api_key().is_empty()
}

fn main() {
    load_dotenv(std::path::Path::new(".env"));
    let model = use_model();
    if !model {
        log("rust-pro: running on rules only (no model)");
    }
    let mut agent: Option<ObserverAgent> = None;
    let stdout = std::io::stdout();
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let message: Value = match serde_json::from_str(&line) {
            Ok(m) => m,
            Err(e) => {
                log(&format!("rust-pro: unreadable message ({e})"));
                continue;
            }
        };
        match message["message_type"].as_str().unwrap_or("") {
            "initialize" => agent = Some(ObserverAgent::new(&message["payload"], model)),
            "decision_request" => {
                // never crash the run: on an internal error wait one slot instead
                let decided = agent.as_mut().and_then(|a| catch_unwind(AssertUnwindSafe(|| a.respond(&message["payload"]))).ok());
                let mut response = Map::new();
                response.insert("protocol_version".into(), json!(PROTOCOL));
                response.insert("message_type".into(), json!("decision_response"));
                response.insert("decision_sequence".into(), message["decision_sequence"].clone());
                response.extend(decided.unwrap_or_else(|| {
                    log("rust-pro: internal error; waiting");
                    wait_for(900.0, "internal error")
                }));
                response.entry("decision_source").or_insert(json!(if model { "llm-advised" } else { "rules" }));
                let mut out = stdout.lock();
                let _ = writeln!(out, "{}", Value::Object(response));
                let _ = out.flush();
            }
            "finish" => {
                let reason = planner::text_of(&message["payload"]["termination_reason"]);
                let (observes, reports, correct) = agent.as_ref().map_or((0, 0, 0), |a| (a.observes, a.faults.reports, a.faults.correct));
                log(&format!("rust-pro finished: {reason}, observes {observes}, reports {reports} ({correct} correct)"));
            }
            _ => {}
        }
    }
}
