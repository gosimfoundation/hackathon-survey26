#!/usr/bin/env node
/**
 * typescript-pro: a readable rule-based example agent for participant-agent-protocol-v4 (Node.js 22+,
 * built-ins only). TypeScript port of examples/python-pro; same strategy, same constants.
 *
 * One JSON object per line on stdin, one per line on stdout, logs on stderr.
 *
 * Per decision request:
 *   1. learn from the last result (planner.onResult) and from new bulletins / observation requests;
 *   2. daytime or rain/storm over the whole sky: wait;
 *   3. instrument-fault rule (FaultWatch below): report when the observed quality collapses;
 *   4. otherwise ask the planner (planner.ts) for a greedy, required-first observe.
 *
 * Optional model stage (logReader.ts): with an API key, the free-text staff notes that some cards attach to
 * observation requests are read once each by the model; announced closures become waits, bad sectors are
 * down-weighted, and announced instrument problems become reports.  Without a key, or when the platform sets
 * OBSERVER_MODEL_DISABLED=1 (an evaluation without a model), the agent runs on its rules alone.
 */
import * as path from "node:path";
import * as readline from "node:readline";
import { LLMClient, apiKey, loadDotenv } from "./llmClient";
import { LogReader } from "./logReader";
import { Json, N_ANCHORS, Planner } from "./planner";
import { formatUtc, parseUtc } from "./skymath";

const PROTOCOL = "participant-agent-protocol-v4";
const NOTE_WAIT_MAX = 120.0; // longest real-time wait for the model's reading of a new staff note (s)

type Action = Json & { action: string };

function log(text: string): void {
  process.stderr.write(text + "\n");
}

/** CPU seconds used by this process so far (Python's time.process_time). */
function processTime(): number {
  const usage = process.cpuUsage();
  return (usage.user + usage.system) / 1e6;
}

/** "YYYY-MM-DD HH:MM" of an epoch-seconds instant (for log lines). */
const shortUtc = (moment: number): string => formatUtc(moment).slice(0, 16).replace("T", " ");

/** One exposure's quality as FaultWatch remembers it. */
interface QualitySample {
  hours: number; // hours since the survey start
  night: number; // night index
  quality: number; // median observed / predicted factor of its hits
  clean: boolean; // taken without all-sky weather
}

/**
 * A simple, conservative instrument-fault rule.
 *
 * The planner gives, after every exposure, the median of observed / predicted factor over its hits
 * ("quality").  A fault multiplies the instrument efficiency by some factor until it is reported; weather
 * and earthquakes lower the quality too, and a report repairs neither.  Weather changes from night to
 * night, a fault stays.  So the rule compares the quality with the usual level since the last repair
 * (90th percentile of exposures without all-sky weather: a clear night with a healthy instrument) and
 * reports on
 *
 *   - a collapse: the last COLLAPSE_RUN exposures all below COLLAPSE_LEVEL x usual, or
 *   - a lasting drop: the median quality of each of the last two observed nights (at least NIGHT_MIN
 *     exposures each, no all-sky weather) below DROP_LEVEL x usual.
 *
 * Only exposures after the last report count as evidence, so one episode is never reported twice.
 * A wrong report is free for the first `false_report_free_allowance` times after each correct one and
 * costs points afterwards; without free reports left the rule waits PAID_SPACING_HOURS between reports
 * (a fault lasts until it is reported, so a late report still pays).
 */
class FaultWatch {
  static readonly COLLAPSE_LEVEL = 0.1;
  static readonly COLLAPSE_RUN = 2;
  static readonly DROP_LEVEL = 0.55;
  static readonly NIGHT_MIN = 4;
  static readonly PAID_SPACING_HOURS = 120.0;
  static readonly MIN_HISTORY = 8;

  private history: QualitySample[] = []; // since the last repair
  private falseSinceCorrect = 0;
  private lastReport = -1e9;
  reports = 0;
  correct = 0;

  constructor(private readonly freeAllowance: number) {}

  add(hours: number, night: number | null, quality: number | null, clean: boolean): void {
    if (quality !== null && night !== null) this.history.push({ hours, night, quality, clean });
  }

  /** The usual quality: 90th percentile of the clean exposures since the last repair. */
  usual(): number | null {
    const values = this.history
      .slice(-400)
      .filter((s) => s.clean)
      .map((s) => s.quality)
      .sort((a, b) => a - b);
    return values.length >= FaultWatch.MIN_HISTORY ? (values[Math.floor((9 * values.length) / 10)] as number) : null;
  }

  /** The reason for a report now, or null. */
  shouldReport(hours: number): string | null {
    const usual = this.usual();
    if (usual === null) return null;
    if (this.falseSinceCorrect >= this.freeAllowance && hours - this.lastReport < FaultWatch.PAID_SPACING_HOURS) return null;
    const fresh = this.history.filter((s) => s.hours > this.lastReport); // evidence since the last report
    const last = fresh.slice(-FaultWatch.COLLAPSE_RUN).map((s) => s.quality);
    if (last.length === FaultWatch.COLLAPSE_RUN && Math.max(...last) < FaultWatch.COLLAPSE_LEVEL * usual) {
      return `quality collapsed to ${((last[last.length - 1] as number) / usual).toFixed(2)} of usual`;
    }
    // median quality per night (clean exposures only), for the last two nights with enough exposures
    const nights = new Map<number, number[]>();
    for (const s of fresh) {
      if (!s.clean) continue;
      const list = nights.get(s.night) ?? [];
      list.push(s.quality);
      nights.set(s.night, list);
    }
    const recent = [...nights.entries()]
      .sort(([a], [b]) => a - b)
      .slice(-2)
      .filter(([, v]) => v.length >= FaultWatch.NIGHT_MIN)
      .map(([, v]) => [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)] as number);
    if (recent.length === 2 && Math.max(...recent) < FaultWatch.DROP_LEVEL * usual) {
      const [a, b] = recent as [number, number];
      return `quality at ${(a / usual).toFixed(2)} and ${(b / usual).toFixed(2)} of usual on two nights`;
    }
    return null;
  }

  reported(hours: number): void {
    this.lastReport = hours;
    this.reports += 1;
  }

  onResult(correct: boolean): void {
    if (correct) {
      this.correct += 1;
      this.falseSinceCorrect = 0;
      this.history = []; // repaired: the usual level is measured afresh
    } else {
      this.falseSinceCorrect += 1;
    }
  }
}

class ObserverAgent {
  readonly planner: Planner;
  private readonly start: number;
  readonly faults: FaultWatch;
  private readonly reader: LogReader | null = null;
  private correctReportAt: number | null = null;
  observes = 0;
  private cpuPerDecision = 0.0;

  constructor(init: Json, useModel: boolean) {
    this.planner = new Planner(init, log);
    this.start = parseUtc(init.survey.start_utc);
    const reporting = init.scoring.reporting ?? {};
    this.faults = new FaultWatch(Math.trunc(Number(reporting.false_report_free_allowance ?? 0)));
    if (useModel) {
      const client = new LLMClient(log);
      this.reader = new LogReader(client, Number(init.site?.utc_offset_hours ?? 0.0), log);
      log(`typescript-pro: model ${client.model} reads staff notes`);
    }
  }

  // --- decision loop -------------------------------------------------------------------------------

  async respond(payload: Json): Promise<Action> {
    const cpuStarted = processTime();
    const action = await this.respondInner(payload);
    const cost = processTime() - cpuStarted;
    this.cpuPerDecision = this.cpuPerDecision === 0 ? cost : 0.95 * this.cpuPerDecision + 0.05 * cost;
    return action;
  }

  private async respondInner(payload: Json): Promise<Action> {
    const now = parseUtc(payload.now_utc);
    const hours = (now - this.start) / 3600.0;
    const planner = this.planner;
    const last: Json = payload.last_result ?? {};
    if (last.action === "report") this.onReportResult(last, now);
    planner.onMessages(payload.new_messages ?? [], payload.latest_bulletin);
    planner.onRequests(payload.active_requests ?? []);
    planner.onResult(payload.last_result);
    this.faults.add(hours, planner.qualityNight, planner.lastQuality, planner.qualityClean);
    this.pace(payload, now);

    const night = planner.currentNight(now);
    if (night === null) {
      const start = planner.nextNightStart(now);
      if (start === null) return { action: "finish", reason: "no observing night left" };
      return { action: "wait", until_utc: formatUtc(start), reason: "daytime" };
    }
    const [nightIndex, nightStart, nightEnd] = night;

    const noteAction = await this.readNotes(payload, now, nightEnd);
    if (noteAction !== null) return noteAction;
    if (nightEnd - now < planner.minExposure) {
      const start = planner.nextNightStart(now);
      if (start === null) return { action: "finish", reason: "survey over" };
      return { action: "wait", until_utc: formatUtc(start), reason: "night ending" };
    }
    if (planner.siteClosed()) {
      return { action: "wait", duration_seconds: this.toNextSlot(now, nightStart), reason: "rain/storm over the whole sky" };
    }

    const why = this.faults.shouldReport(hours);
    if (why !== null) {
      this.faults.reported(hours);
      log(`typescript-pro: report at ${payload.now_utc} (${why})`);
      return { action: "report", reason: why };
    }

    const action = planner.plan(now, nightEnd, nightIndex);
    if (action === null) {
      return { action: "wait", duration_seconds: this.toNextSlot(now, nightStart), reason: "nothing useful is up" };
    }
    this.observes += 1;
    action.reason = `${Object.keys(action.assignments).length} fibres, ${action.duration_seconds} s, ${action.program}`;
    return action;
  }

  /** Seconds to the next slot boundary of the night (between 1 and 60 minutes). */
  private toNextSlot(now: number, nightStart: number): number {
    const slot = this.planner.slotSeconds;
    return Math.trunc(Math.max(60, Math.min(3600, slot - ((now - nightStart) % slot))));
  }

  private onReportResult(result: Json, now: number): void {
    const correct = Boolean(result.correct);
    this.faults.onResult(correct);
    if (correct) {
      this.correctReportAt = now;
      this.planner.resetQuality();
    }
    log(`typescript-pro: report ${correct ? "correct, fault repaired" : "wrong"} (delta ${result.score_delta})`);
  }

  // --- pace ----------------------------------------------------------------------------------------

  /** Keep the planner cheap enough for the CPU budget: fewer anchors when time runs short. */
  private pace(payload: Json, now: number): void {
    const wall: Json = payload.wallclock ?? {};
    const cpuLeft = Number(wall.remaining_real_cpu_seconds ?? wall.remaining_seconds ?? 1e9);
    let nightLeft = 0.0;
    for (const [start, end] of this.planner.nights) if (end > now) nightLeft += Math.max(0.0, end - Math.max(start, now));
    const budget = (0.6 * cpuLeft) / Math.max(1.0, nightLeft / 900.0); // about one decision per 15 night minutes
    if (this.cpuPerDecision > budget) {
      this.planner.nAnchors = Math.max(1, this.planner.nAnchors - 1);
    } else if (this.cpuPerDecision < 0.5 * budget && this.planner.nAnchors < N_ANCHORS) {
      this.planner.nAnchors += 1;
    }
  }

  // --- optional: staff notes read by the model (logReader.ts) --------------------------------------

  private async readNotes(payload: Json, now: number, nightEnd: number): Promise<Action | null> {
    const reader = this.reader;
    if (reader === null) return null;
    const requests: Json[] = [
      ...(payload.active_requests ?? []),
      ...((payload.new_messages ?? []) as Json[]).filter((m) => m.record_type === "observation_request"),
    ];
    const wallLeft = Number(payload.wallclock?.wall_remaining_seconds ?? 1e9);
    if (reader.feed(requests, now, wallLeft) > 0) {
      await reader.wait(Math.min(NOTE_WAIT_MAX, 0.02 * wallLeft)); // waiting costs real time only, no CPU budget
    }
    reader.collect();
    this.planner.logAvoid = reader.avoidNow(now);
    const since = reader.reportDue(now);
    if (since !== null && (this.correctReportAt === null || this.correctReportAt < since)) {
      this.faults.reported((now - this.start) / 3600.0);
      log(`typescript-pro: report at ${payload.now_utc} (staff note: instrument problem from ${shortUtc(since)})`);
      return { action: "report", reason: "staff note: instrument problem" };
    }
    const end = reader.closed(now);
    if (end !== null) {
      const seconds = Math.trunc(Math.max(60, Math.min(end - now, nightEnd - now, 3600)));
      return { action: "wait", duration_seconds: seconds, reason: "staff note: site closed" };
    }
    return null;
  }
}

/** Model only with a key, and never when the platform runs this evaluation without a model. */
function useModel(): boolean {
  return process.env.OBSERVER_MODEL_DISABLED !== "1" && Boolean(apiKey());
}

async function main(): Promise<number> {
  loadDotenv(path.join(__dirname, "..", ".env"));
  const model = useModel();
  if (!model) log("typescript-pro: running on rules only (no model)");
  let agent: ObserverAgent | null = null;
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    const message = JSON.parse(line);
    const kind = message.message_type;
    if (kind === "initialize") {
      agent = new ObserverAgent(message.payload, model);
    } else if (kind === "decision_request") {
      let action: Action;
      try {
        if (agent === null) throw new Error("decision_request before initialize");
        action = await agent.respond(message.payload);
      } catch (exc) {
        // never crash the run: wait one slot instead
        log(`typescript-pro: error ${exc instanceof Error ? `${exc.name}: ${exc.message}` : String(exc)}; waiting`);
        action = { action: "wait", duration_seconds: 900, reason: "internal error" };
      }
      if (!("decision_source" in action)) action.decision_source = model ? "llm-advised" : "rules";
      const response = { protocol_version: PROTOCOL, message_type: "decision_response", decision_sequence: message.decision_sequence, ...action };
      process.stdout.write(JSON.stringify(response) + "\n");
    } else if (kind === "finish") {
      const payload = message.payload ?? {};
      log(
        `typescript-pro finished: ${payload.termination_reason}, observes ${agent?.observes ?? 0}, ` +
          `reports ${agent?.faults.reports ?? 0} (${agent?.faults.correct ?? 0} correct)`,
      );
    }
  }
  return 0;
}

main().then(
  (code) => process.stdout.write("", () => process.exit(code)), // background model calls must not keep the process alive
  (exc) => {
    log(`typescript-pro: fatal ${exc instanceof Error ? exc.stack : String(exc)}`);
    process.exit(1);
  },
);
