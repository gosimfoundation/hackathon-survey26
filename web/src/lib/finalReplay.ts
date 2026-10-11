/**
 * Every ranked team's held-out replays (owner 10-10: all teams, every card), stored compactly outside the bundle.
 *
 * final-audit/gen_replay_compact.py writes, per card, one base file (site, whole catalogue, weather) and, per run,
 * its actions column-wise with targets as catalogue indices, all gzip'd JSON:
 *   <base>/cards/<card>.json.gz   <base>/runs/<run_id>.json.gz
 * content/final/replay-index.json lists the runs that have one ({run_id: card}). expandReplay rebuilds the exact
 * RawReplay the generator started from (the generator checks that round trip for every file).
 */
import type { RawReplay, RawReplayAction, RawReplayTarget, RawReplaySlot } from '../composables/useReplayClock'
import index from '../content/final/replay-index.json'

export interface ReplayCardBase { site: RawReplay['site']; targets: RawReplayTarget[]; weather: RawReplaySlot[] }
export interface CompactRun {
  v: 2
  used?: number[]
  unused?: number[]
  score: RawReplay['score']
  completed: number
  required_missing: string[]
  nights: number
  actions: {
    i: string[]; slot: number[]; a: string[]; program: string[]; cls: string[]; t: string[]; dt: number[]
    score: number[]; penalty: number[]; center: ([number, number] | null)[]; targets: number[][]
  }
}

const runs = index as Record<string, string>
/** Where the compact files are served from: VITE_FINAL_REPLAY_BASE, else <site base>/final-replays. */
const BASE = (import.meta.env.VITE_FINAL_REPLAY_BASE as string | undefined)?.replace(/\/+$/, '')
  || `${import.meta.env.BASE_URL.replace(/\/+$/, '')}/final-replays`

export function hasCompactReplay(runId: string): boolean {
  return runId in runs
}

async function gunzipJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok || !res.body) throw new Error(`replay ${res.status}`)
  // Hosts may already have undone the gzip (Content-Encoding); a gzip stream starts with 0x1f 0x8b.
  const buf = new Uint8Array(await res.arrayBuffer())
  if (buf[0] !== 0x1f || buf[1] !== 0x8b) return JSON.parse(new TextDecoder().decode(buf)) as T
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))
  return JSON.parse(await new Response(stream).text()) as T
}

const bases = new Map<string, Promise<ReplayCardBase>>()

export function expandReplay(base: ReplayCardBase, run: CompactRun): RawReplay {
  const c = run.actions
  const actions: RawReplayAction[] = c.i.map((i, k) => ({
    i, slot: base.weather[c.slot[k]].slot, a: c.a[k], program: c.program[k],
    targets: c.targets[k].map(j => base.targets[j].id),
    center: c.center[k] ? { ra: c.center[k]![0], dec: c.center[k]![1] } : null,
    t: c.t[k], dt: c.dt[k], score: c.score[k], penalty: c.penalty[k], cls: c.cls[k],
  }))
  let shown: RawReplayTarget[]
  if (run.used) shown = run.used.map(j => base.targets[j])
  else { const skip = new Set(run.unused ?? []); shown = base.targets.filter((_, j) => !skip.has(j)) }
  return {
    site: base.site, targets: shown, weather: base.weather, actions,
    score: run.score, completed: run.completed, required_missing: run.required_missing, nights: run.nights,
  }
}

export async function loadCompactReplay(runId: string): Promise<RawReplay | null> {
  const card = runs[runId]
  if (!card) return null
  let base = bases.get(card)
  if (!base) {
    base = gunzipJson<ReplayCardBase>(`${BASE}/cards/${card}.json.gz`)
    bases.set(card, base)
    base.catch(() => bases.delete(card))
  }
  const [b, run] = await Promise.all([base, gunzipJson<CompactRun>(`${BASE}/runs/${runId}.json.gz`)])
  return expandReplay(b, run)
}
