/**
 * Optional model stage: read the free-text notes that come with observation requests.
 *
 * Some task cards attach a longer `reason` text to observation requests: notes from the observatory staff. They
 * can mention things that matter for the survey (closures, weather, instrument trouble, instructions). This
 * module sends every new note once to the configured model, together with a few earlier notes as context and
 * the current time, and asks for a small JSON summary of operational facts with times. agent.ts turns the
 * answer into actions with three plain rules:
 *
 *     closures   -> wait while the whole site is announced closed
 *     avoid      -> down-weight the named compass sectors during the announced window
 *     report_at  -> send a `report` once the staff say the instrument itself has a problem (now or from an
 *                   announced time), or when they explicitly ask for a problem report at a time
 *
 * Calls run in the background as promises (the decision loop never needs the answer to continue), are cached
 * per message, retried with backoff on HTTP 429 / 5xx, and simply skipped after errors. Short labels such as
 * "time-critical follow-up" are not notes and are never sent. Port of python-pro/log_reader.py (same prompt).
 */
import { Json, LLMClient, RetryableError } from "./llmClient";

const DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const MIN_NOTE_CHARS = 31; // shorter reasons are labels, not notes
const CONTEXT_NOTES = 4; // earlier notes sent along as context
const CONTEXT_CHARS = 6000;
const CALL_DEADLINE = 360.0; // give up on one note after this many seconds (retries included)
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const SYSTEM =
  "You help run a robotic survey telescope. You get one new note from the observatory staff (shift log, chat " +
  "or a relayed message), a few earlier notes as context, the current time and the site's offset from UTC. " +
  "Extract only operational facts that matter for observing, each with its time window. Read carefully: " +
  "the notes may be informal, mix languages, and contain corrections; a later statement replaces an earlier " +
  "one about the same thing. Ignore hearsay, jokes and anything about other sites. Leave a list empty when unsure.\n" +
  "Convert every time to UTC and write it as YYYY-MM-DDTHH:MM. Lists:\n" +
  "closures: windows in which the whole telescope will not observe (dome closed, maintenance, shutdown, " +
  "closed for weather). Not for conditions the note calls fine to observe.\n" +
  "avoid: windows in which named parts of the sky (compass sectors N NE E SE S SW W NW, or ALL) cannot be " +
  "observed usefully (thick cloud, rain, wind, other activity). Not for conditions the note calls fine.\n" +
  "report_at: moments from which the staff say the telescope's own instrument is degraded or misbehaving " +
  "(already happening, or announced for a future time), or at which they explicitly ask for an instrument " +
  "problem report. Not weather, and not earthquakes (a report does not repair those). Only facts stated in " +
  "the NEW note.\n" +
  'Reply with one JSON object only: {"closures": [{"start_utc": "...", "end_utc": "..."}], ' +
  '"avoid": [{"start_utc": "...", "end_utc": "...", "directions": ["SW", ...]}], ' +
  '"report_at": [{"utc": "...", "why": "<10 words"}], "summary": "<20 words"}';

const monotonic = (): number => performance.now() / 1000;
const sleep = (seconds: number) => new Promise<void>((resolve) => setTimeout(resolve, Math.max(0, seconds) * 1000));

/** "YYYY-MM-DDTHH:MM" (or with a space, seconds, zone after the minutes) -> epoch seconds, or null. */
function utc(text: unknown): number | null {
  const head = String(text ?? "").trim().slice(0, 16).replace(/ /g, "T");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(head)) return null;
  const ms = Date.parse(head + ":00Z");
  return Number.isNaN(ms) ? null : ms / 1000;
}

/** Epoch seconds -> "YYYY-MM-DDTHH:MM". */
const minutes = (moment: number): string => new Date(Math.floor(moment) * 1000).toISOString().slice(0, 16);

export class LogReader {
  private readonly offset: number; // seconds
  readonly seen = new Set<unknown>(); // request ids already sent (cache per note)
  private readonly notes: string[] = []; // earlier note texts (context)
  private answers: [unknown, number, Json][] = []; // (request id, issued, answer) not yet applied
  private readonly running = new Set<Promise<void>>();
  private active = 0; // calls holding one of the `workers` slots
  private readonly queue: (() => void)[] = [];
  // the facts so far
  private readonly closures: [number, number][] = [];
  private readonly avoid: [number, number, Set<string>][] = [];
  private readonly reportTimes: number[] = []; // not yet acted on

  constructor(
    private readonly client: LLMClient,
    utcOffsetHours: number,
    private readonly log: (text: string) => void = () => {},
    private readonly workers = 2,
  ) {
    this.offset = utcOffsetHours * 3600;
  }

  // --- input ---------------------------------------------------------------------------------------

  /** Start reading every note not seen before; returns how many were started. */
  feed(requests: Json[], now: number, wallclockLeft: number): number {
    let started = 0;
    for (const request of requests) {
      const rid = request.request_id;
      const text = String(request.reason ?? "").trim();
      if (this.seen.has(rid) || text.length < MIN_NOTE_CHARS) continue;
      this.seen.add(rid);
      const context: string[] = [];
      for (const note of this.notes.slice(-CONTEXT_NOTES).reverse()) {
        if (context.reduce((n, c) => n + c.length, 0) + note.length > CONTEXT_CHARS) break;
        context.unshift(note);
      }
      this.notes.push(text);
      const issued = utc(request.issued_at_utc) ?? now;
      const local = now + this.offset;
      const user = {
        now_utc: minutes(now),
        now_local: `${minutes(local)} (${WEEKDAYS[new Date(local * 1000).getUTCDay()]})`,
        site_utc_offset_hours: this.offset / 3600,
        note_issued_utc: minutes(issued),
        earlier_notes: context,
        new_note: text,
      };
      const deadline = Math.min(CALL_DEADLINE, wallclockLeft - 60.0);
      if (deadline < 10.0) continue;
      const call = this.run(rid, issued, user, deadline).finally(() => this.running.delete(call));
      this.running.add(call);
      started += 1;
    }
    return started;
  }

  private async run(rid: unknown, issued: number, user: Json, deadline: number): Promise<void> {
    const started = monotonic();
    const left = () => deadline - (monotonic() - started);
    let answer: Json | null = null;
    let delay = 5.0;
    if (this.active < this.workers) this.active += 1;
    else await new Promise<void>((resolve) => this.queue.push(resolve)); // a finishing call hands its slot over
    try {
      while (left() > 0) {
        try {
          answer = await this.client.request(SYSTEM, user, Math.min(240.0, left()), 12000);
          break;
        } catch (exc) {
          if (!(exc instanceof RetryableError)) break; // auth / quota / bad request: retrying will not help
        }
        await sleep(Math.min(delay * (0.75 + 0.5 * Math.random()), Math.max(0.0, left())));
        delay = Math.min(delay * 2, 60.0);
      }
    } finally {
      const next = this.queue.shift();
      if (next) next();
      else this.active -= 1;
    }
    if (answer !== null) this.answers.push([rid, issued, answer]);
    else this.log(`log reader: no answer for request ${rid}; rules decide`);
  }

  /** Wait (free of CPU) up to `seconds` for notes still being read. */
  async wait(seconds: number): Promise<void> {
    if (this.running.size === 0 || seconds <= 0) return;
    let timer: NodeJS.Timeout | undefined;
    await Promise.race([Promise.all(this.running), new Promise<void>((resolve) => (timer = setTimeout(resolve, seconds * 1000)))]);
    clearTimeout(timer);
  }

  // --- answers -> facts ----------------------------------------------------------------------------

  collect(): void {
    const answers = this.answers;
    this.answers = [];
    for (const [rid, issued, answer] of answers) this.apply(rid, issued, answer);
  }

  private apply(rid: unknown, issued: number, answer: Json): void {
    const items = (key: string): Json[] => {
      const value = answer[key];
      return Array.isArray(value) ? value.filter((x): x is Json => x !== null && typeof x === "object" && !Array.isArray(x)) : [];
    };
    for (const c of items("closures")) {
      const [start, end] = [utc(c.start_utc), utc(c.end_utc)];
      if (start !== null && end !== null && end > start && end - start <= 10 * 86400) this.closures.push([start, end]);
    }
    for (const a of items("avoid")) {
      const [start, end] = [utc(a.start_utc), utc(a.end_utc)];
      const listed: unknown[] = Array.isArray(a.directions) ? a.directions : [];
      const dirs = new Set(listed.includes("ALL") ? DIRECTIONS : DIRECTIONS.filter((d) => listed.includes(d)));
      if (start !== null && end !== null && end > start && dirs.size > 0) this.avoid.push([start, end, dirs]);
    }
    for (const r of items("report_at")) {
      const t = utc(r.utc);
      // stated now or announced for later; ignore stale or far-off times, and duplicates
      if (t !== null && issued - 24 * 3600 <= t && t <= issued + 60 * 86400 && this.reportTimes.every((x) => Math.abs(t - x) > 3600)) {
        this.reportTimes.push(t);
      }
    }
    this.log(
      `log reader ${rid}: ${String(answer.summary ?? "").slice(0, 100)} | closures ${items("closures").length} ` +
        `avoid ${items("avoid").length} report_at ${JSON.stringify(items("report_at").map((r) => String(r.utc)))}`,
    );
  }

  /** End of the announced closure covering `now`, or null. */
  closed(now: number): number | null {
    const ends = this.closures.filter(([start, end]) => start <= now && now < end).map(([, end]) => end);
    return ends.length > 0 ? Math.max(...ends) : null;
  }

  avoidNow(now: number): Set<string> {
    const out = new Set<string>();
    for (const [start, end, dirs] of this.avoid) if (start <= now && now < end) for (const d of dirs) out.add(d);
    return out;
  }

  /** The earliest announced problem time that has arrived (and is recent), removed from the list. */
  reportDue(now: number): number | null {
    const due = this.reportTimes.filter((t) => t <= now).sort((a, b) => a - b);
    for (const t of due) this.reportTimes.splice(this.reportTimes.indexOf(t), 1);
    const recent = due.filter((t) => now - t <= 24 * 3600);
    return recent.length > 0 ? (recent[0] as number) : null;
  }
}
