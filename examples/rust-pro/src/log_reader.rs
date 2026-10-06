//! Optional model stage: read the free-text notes that come with observation requests. Port of
//! `python-pro/log_reader.py`.
//!
//! Some task cards attach a longer `reason` text to observation requests: notes from the observatory staff. They
//! can mention things that matter for the survey (closures, weather, instrument trouble, instructions). This
//! module sends every new note once to the configured model, together with a few earlier notes as context and
//! the current time, and asks for a small JSON summary of operational facts with times. main.rs turns the
//! answer into actions with three plain rules:
//!
//! ```text
//! closures   -> wait while the whole site is announced closed
//! avoid      -> down-weight the named compass sectors during the announced window
//! report_at  -> send a `report` once the staff say the instrument itself has a problem (now or from an
//!               announced time), or when they explicitly ask for a problem report at a time
//! ```
//!
//! Calls run on background threads (the decision loop never needs the answer to continue), are cached per
//! message, retried with backoff on HTTP 429 / 5xx, and simply skipped without a key or after errors. Short
//! labels such as "time-critical follow-up" are not notes and are never sent.

use serde_json::{json, Map, Value};
use std::collections::hash_map::RandomState;
use std::collections::{BTreeSet, HashSet};
use std::hash::{BuildHasher, Hasher};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crate::llm_client::{Endpoint, Failure};
use crate::log;
use crate::skymath::{format_utc, parse_utc};

const DIRECTIONS: [&str; 8] = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const MIN_NOTE_CHARS: usize = 31; // shorter reasons are labels, not notes
const CONTEXT_NOTES: usize = 4; // earlier notes sent along as context
const CONTEXT_CHARS: usize = 6000;
const CALL_DEADLINE: f64 = 360.0; // give up on one note after this many seconds (retries included)
const WORKERS: usize = 2; // notes read at the same time
const DAY: f64 = 86400.0;

const SYSTEM: &str = concat!(
    "You help run a robotic survey telescope. You get one new note from the observatory staff (shift log, chat ",
    "or a relayed message), a few earlier notes as context, the current time and the site's offset from UTC. ",
    "Extract only operational facts that matter for observing, each with its time window. Read carefully: ",
    "the notes may be informal, mix languages, and contain corrections; a later statement replaces an earlier ",
    "one about the same thing. Ignore hearsay, jokes and anything about other sites. Leave a list empty when unsure.\n",
    "Convert every time to UTC and write it as YYYY-MM-DDTHH:MM. Lists:\n",
    "closures: windows in which the whole telescope will not observe (dome closed, maintenance, shutdown, ",
    "closed for weather).\n",
    "avoid: windows in which named parts of the sky (compass sectors N NE E SE S SW W NW, or ALL) cannot be ",
    "observed usefully (thick cloud, rain, wind, other activity). Not for conditions the note calls fine.\n",
    "report_at: moments from which the staff say the telescope's own instrument is degraded or misbehaving ",
    "(already happening, or announced for a future time), or at which they explicitly ask for an instrument ",
    "problem report. Not weather, and not earthquakes (a report does not repair those). Only facts stated in ",
    "the NEW note.\n",
    "Reply with one JSON object only: {\"closures\": [{\"start_utc\": \"...\", \"end_utc\": \"...\"}], ",
    "\"avoid\": [{\"start_utc\": \"...\", \"end_utc\": \"...\", \"directions\": [\"SW\", ...]}], ",
    "\"report_at\": [{\"utc\": \"...\", \"why\": \"<10 words\"}], \"summary\": \"<20 words\"}"
);

/// "YYYY-MM-DDTHH:MM" (or with a space) -> epoch seconds; None when it is not a valid time.
fn utc_minute(value: Option<&Value>) -> Option<f64> {
    let text: String = value?.as_str()?.trim().chars().take(16).collect::<String>().replace(' ', "T");
    let moment = parse_utc(&format!("{text}:00Z"));
    (text.len() == 16 && format_utc(moment)[..16] == text).then_some(moment)
}

/// "YYYY-MM-DDTHH:MM" of a moment.
fn minute(moment: f64) -> String {
    format_utc(moment)[..16].to_string()
}

/// A JSON value as Python's str() would show it (strings without quotes).
fn text_of(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => "None".into(),
        Some(Value::String(s)) => s.clone(),
        Some(v) => v.to_string(),
    }
}

/// A random factor in [0.75, 1.25) for backoff jitter (std only: RandomState is randomly seeded).
fn jitter() -> f64 {
    let bits = RandomState::new().build_hasher().finish();
    0.75 + 0.5 * (bits >> 11) as f64 / (1u64 << 53) as f64
}

#[derive(Default)]
struct Shared {
    pending: usize,
    active: usize,                                   // calls holding one of the WORKERS slots
    answers: Vec<(String, f64, Map<String, Value>)>, // (request id, issued, answer) not yet applied
}

pub struct LogReader {
    endpoint: Endpoint,
    offset: f64,                  // site offset from UTC (s)
    pub seen: HashSet<String>,    // request ids already sent (cache per note)
    notes: Vec<String>,           // earlier note texts (context)
    shared: Arc<(Mutex<Shared>, Condvar)>,
    // the facts so far
    closures: Vec<(f64, f64)>,
    avoid: Vec<(f64, f64, BTreeSet<String>)>,
    report_times: Vec<f64>, // not yet acted on
}

impl LogReader {
    pub fn new(endpoint: Endpoint, utc_offset_hours: f64) -> LogReader {
        LogReader {
            endpoint,
            offset: utc_offset_hours * 3600.0,
            seen: HashSet::new(),
            notes: Vec::new(),
            shared: Arc::new((Mutex::new(Shared::default()), Condvar::new())),
            closures: Vec::new(),
            avoid: Vec::new(),
            report_times: Vec::new(),
        }
    }

    // --- input -------------------------------------------------------------------------------------------

    /// Start reading every note not seen before; returns how many were started.
    pub fn feed(&mut self, requests: &[&Value], now: f64, wallclock_left: f64) -> usize {
        let mut started = 0;
        for request in requests {
            let rid = text_of(request.get("request_id"));
            let text = request.get("reason").and_then(Value::as_str).unwrap_or("").trim().to_string();
            if self.seen.contains(&rid) || text.chars().count() < MIN_NOTE_CHARS {
                continue;
            }
            self.seen.insert(rid.clone());
            let mut context: Vec<String> = Vec::new();
            for note in self.notes[self.notes.len().saturating_sub(CONTEXT_NOTES)..].iter().rev() {
                if context.iter().map(|c| c.chars().count()).sum::<usize>() + note.chars().count() > CONTEXT_CHARS {
                    break;
                }
                context.insert(0, note.clone());
            }
            self.notes.push(text.clone());
            let issued = utc_minute(request.get("issued_at_utc")).unwrap_or(now);
            let local = now + self.offset;
            let weekday = ["Thursday", "Friday", "Saturday", "Sunday", "Monday", "Tuesday", "Wednesday"]
                [(local / DAY).floor().rem_euclid(7.0) as usize];
            let user = json!({
                "now_utc": minute(now),
                "now_local": format!("{} ({weekday})", minute(local)),
                "site_utc_offset_hours": self.offset / 3600.0,
                "note_issued_utc": minute(issued),
                "earlier_notes": context,
                "new_note": text,
            });
            let deadline = CALL_DEADLINE.min(wallclock_left - 60.0);
            if deadline < 10.0 {
                continue;
            }
            if let Ok(mut state) = self.shared.0.lock() {
                state.pending += 1;
            }
            let (endpoint, shared) = (self.endpoint.clone(), self.shared.clone());
            thread::spawn(move || run(endpoint, shared, rid, issued, user, deadline));
            started += 1;
        }
        started
    }

    /// Wait (free of CPU) up to `seconds` for notes still being read.
    pub fn wait(&self, seconds: f64) {
        let (lock, cvar) = &*self.shared;
        let deadline = Instant::now() + Duration::from_secs_f64(seconds.max(0.0));
        let Ok(mut state) = lock.lock() else { return };
        while state.pending > 0 {
            let now = Instant::now();
            if now >= deadline {
                return;
            }
            state = match cvar.wait_timeout(state, deadline - now) {
                Ok((s, _)) => s,
                Err(_) => return,
            };
        }
    }

    // --- answers -> facts ------------------------------------------------------------------------------

    pub fn collect(&mut self) {
        let answers = match self.shared.0.lock() {
            Ok(mut state) => std::mem::take(&mut state.answers),
            Err(_) => return,
        };
        for (rid, issued, answer) in answers {
            self.apply(&rid, issued, &answer);
        }
    }

    fn apply(&mut self, rid: &str, issued: f64, answer: &Map<String, Value>) {
        let items = |key: &str| -> Vec<&Map<String, Value>> {
            answer.get(key).and_then(Value::as_array).map_or(Vec::new(), |a| a.iter().filter_map(Value::as_object).collect())
        };
        for c in items("closures") {
            if let (Some(start), Some(end)) = (utc_minute(c.get("start_utc")), utc_minute(c.get("end_utc"))) {
                if end > start && end - start <= 10.0 * DAY {
                    self.closures.push((start, end));
                }
            }
        }
        for a in items("avoid") {
            let listed: Vec<&str> = a.get("directions").and_then(Value::as_array).map_or(Vec::new(), |d| d.iter().filter_map(Value::as_str).collect());
            let dirs: BTreeSet<String> = DIRECTIONS
                .iter()
                .filter(|d| listed.contains(&"ALL") || listed.contains(d))
                .map(|d| d.to_string())
                .collect();
            if let (Some(start), Some(end)) = (utc_minute(a.get("start_utc")), utc_minute(a.get("end_utc"))) {
                if end > start && !dirs.is_empty() {
                    self.avoid.push((start, end, dirs));
                }
            }
        }
        for r in items("report_at") {
            // stated now or announced for later; ignore stale or far-off times, and duplicates
            if let Some(t) = utc_minute(r.get("utc")) {
                if issued - DAY <= t && t <= issued + 60.0 * DAY && self.report_times.iter().all(|x| (t - x).abs() > 3600.0) {
                    self.report_times.push(t);
                }
            }
        }
        let summary: String = answer.get("summary").map_or(String::new(), |v| text_of(Some(v))).chars().take(100).collect();
        let report_at: Vec<String> = items("report_at").iter().map(|r| text_of(r.get("utc"))).collect();
        log(&format!(
            "log reader {rid}: {summary} | closures {} avoid {} report_at {report_at:?}",
            items("closures").len(),
            items("avoid").len()
        ));
    }

    /// End of the announced closure covering `now`, or None.
    pub fn closed(&self, now: f64) -> Option<f64> {
        self.closures.iter().filter(|&&(s, e)| s <= now && now < e).map(|&(_, e)| e).reduce(f64::max)
    }

    pub fn avoid_now(&self, now: f64) -> BTreeSet<String> {
        self.avoid.iter().filter(|(s, e, _)| *s <= now && now < *e).flat_map(|(_, _, d)| d.iter().cloned()).collect()
    }

    /// The earliest announced problem time that has arrived (and is recent), removed from the list.
    pub fn report_due(&mut self, now: f64) -> Option<f64> {
        let mut due: Vec<f64> = self.report_times.iter().cloned().filter(|&t| t <= now).collect();
        due.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        self.report_times.retain(|&t| t > now);
        due.into_iter().find(|&t| now - t <= DAY)
    }
}

/// One note on a background thread: at most WORKERS at a time, retried with backoff on 429 / 5xx and network
/// errors, given up on other HTTP errors or after `deadline` seconds (the wait for a slot included).
fn run(endpoint: Endpoint, shared: Arc<(Mutex<Shared>, Condvar)>, rid: String, issued: f64, user: Value, deadline: f64) {
    let started = Instant::now();
    let left = || deadline - started.elapsed().as_secs_f64();
    let (lock, cvar) = &*shared;
    if let Ok(mut state) = lock.lock() {
        while state.active >= WORKERS {
            state = match cvar.wait(state) {
                Ok(s) => s,
                Err(_) => return,
            };
        }
        state.active += 1;
    }
    let mut answer = None;
    let mut delay = 5.0f64;
    while left() > 0.0 {
        match endpoint.request(SYSTEM, &user, left().min(240.0), 12000) {
            Ok(a) => {
                answer = Some(a);
                break;
            }
            // auth / quota / bad request: retrying will not help
            Err(Failure::Retry(_, _, code)) if (400..500).contains(&code) && code != 429 => break,
            Err(_) => {}
        }
        thread::sleep(Duration::from_secs_f64((delay * jitter()).min(left().max(0.0))));
        delay = (delay * 2.0).min(60.0);
    }
    if let Ok(mut state) = lock.lock() {
        match answer {
            Some(a) => state.answers.push((rid, issued, a)),
            None => log(&format!("log reader: no answer for request {rid}; rules decide")),
        }
        state.active -= 1;
        state.pending -= 1;
    }
    cvar.notify_all();
}
