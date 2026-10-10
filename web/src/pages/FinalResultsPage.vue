<script setup lang="ts">
/**
 * Hidden-final results page (local style preview, 10-09 owner: rankings + scores + click-through
 * run details only; no review section). Reads the static snapshot content/final/results.json
 * (gen_final_preview.py); live data wiring comes after the style is approved.
 * TODO(preview): strings are hard-coded zh; move to i18n before publishing.
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import PageHead from '../components/layout/PageHead.vue'
import SkyConsole from '../components/sections/SkyConsole.vue'
import { hasRunReplay, loadRunReplay, resetToDemoReplay } from '../composables/useReplayClock'
import results from '../content/final/results.json'

interface RunRow {
  run_id: string; card: string; status: string; score: number | null
  started_at: string | null; finished_at: string | null
  termination: string | null; reruns: number; result_path: string | null
  counted?: boolean
}
interface TeamRow {
  team_id: string; name: string; rank: number; total: number
  cards: Record<string, number | null>; runs: RunRow[]; best_of?: boolean
}

const cards = results.cards as string[]
const teams = results.teams as unknown as TeamRow[]
const generatedAt = results.generated_at
const selected = ref<TeamRow | null>(null)

// embedded: rendered inside LeaderboardPage's own scaffold — no own header, background or page padding
// (10-10 owner review: the dark box edges showed as stray lines inside the outer page).
const props = defineProps<{ embedded?: boolean }>()

const cardLabel = (c: string) => c.replace('v4-', '').toUpperCase()
const num = (v: number | null | undefined) =>
  v == null ? '—' : Math.round(v).toLocaleString('en-US')
const fmtTime = (ts: string | null) => {
  if (!ts) return '—'
  const d = new Date(ts)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const dur = (r: RunRow) => {
  if (!r.started_at || !r.finished_at) return '—'
  const m = Math.round((+new Date(r.finished_at) - +new Date(r.started_at)) / 60000)
  return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : `${m}m`
}
const statusLabel = (s: string) =>
  ({ scored: '已出分', failed: '失败', cancelled: '已取消', running: '在跑', queued: '排队' }[s] ?? s)

const runsOf = computed(() => {
  if (!selected.value) return new Map<string, RunRow[]>()
  const m = new Map<string, RunRow[]>()
  for (const r of selected.value.runs) {
    if (!m.has(r.card)) m.set(r.card, [])
    m.get(r.card)!.push(r)
  }
  return m
})

// --- 3D replay embedded from the homepage console ---------------------------------------------
// One selector over the four cards; each card plays back its highest-scoring scored run. The
// replay files (content/final/replays/<run_id>.json) may still be generating — a missing one gets
// a placeholder instead of the console.
type ReplayState = 'idle' | 'loading' | 'ready' | 'pending'
const replayCard = ref<string>('')
const replayState = ref<ReplayState>('idle')
let replayToken = 0

// Replay files (content/final/replays/<run_id>.json) are still generating one by one, so a card's
// pick is its highest-scoring run *among those with a replay file*; a card with none shows 回放生成中.
const bestRunOf = (card: string): RunRow | null => {
  const runs = (runsOf.value.get(card) ?? []).filter(r => hasRunReplay(r.run_id))
  if (!runs.length) return null
  const scored = runs.filter(r => r.status === 'scored' && r.score != null)
  const pool = scored.length ? scored : runs
  return pool.reduce<RunRow | null>((best, r) =>
    best == null || (r.score ?? -Infinity) > (best.score ?? -Infinity) ? r : best, null)
}

async function loadCardReplay() {
  const token = ++replayToken
  const run = replayCard.value ? bestRunOf(replayCard.value) : null
  if (!run) { replayState.value = 'pending'; return }
  replayState.value = 'loading'
  const ok = await loadRunReplay(run.run_id)
  if (token !== replayToken) return  // the user picked another card or closed the dialog meanwhile
  replayState.value = ok ? 'ready' : 'pending'
}

watch(selected, team => {
  replayToken += 1  // invalidate any in-flight load
  if (!team) {
    replayCard.value = ''
    replayState.value = 'idle'
    void resetToDemoReplay()  // hand the shared clock back to the demo run (footer, homepage)
    return
  }
  // Default to the card of the team's best-scoring run that has a replay file (any best run else).
  let best: RunRow | null = null
  let bestAny: RunRow | null = null
  for (const r of team.runs) {
    if (r.status !== 'scored' || r.score == null) continue
    if (bestAny == null || r.score > (bestAny.score ?? -Infinity)) bestAny = r
    if (hasRunReplay(r.run_id) && (best == null || r.score > (best.score ?? -Infinity))) best = r
  }
  replayCard.value = (best ?? bestAny)?.card ?? cards[0] ?? ''
})
watch(replayCard, () => { if (selected.value) void loadCardReplay() })
onUnmounted(() => { void resetToDemoReplay() })
</script>

<template>
  <main :class="props.embedded ? '' : 'final-results'">
    <section :class="props.embedded ? '' : 'section'">
      <div :class="props.embedded ? '' : 'wrap'">
        <PageHead v-if="!props.embedded" kicker="HIDDEN FINAL · E–H" title="决赛成绩"
          lede="每队每张卡跑 3 次取平均，四张卡再平均。点队名看 12 次明细。"
          :note="`数据快照 ${generatedAt}（本地预览）`" />

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>名次</th><th>队伍</th><th class="r">总分</th>
                <th v-for="c in cards" :key="c" class="r">{{ cardLabel(c) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in teams" :key="t.team_id" class="team-row" @click="selected = t">
                <td><span class="rank" :class="`rank-${Math.min(t.rank, 3)}`">#{{ t.rank }}</span></td>
                <td class="name">{{ t.name }}</td>
                <td class="r num total">{{ num(t.total) }}</td>
                <td v-for="c in cards" :key="c" class="r num">{{ num(t.cards[c]) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <div v-if="selected" class="team-detail" @click.self="selected = null">
      <section class="team-detail-panel" role="dialog" aria-modal="true" :aria-label="selected.name">
        <header class="team-detail-head">
          <span class="team-detail-rank" :class="`rank-${Math.min(selected.rank, 3)}`">#{{ selected.rank }}</span>
          <h2 class="team-detail-name">{{ selected.name }}</h2>
          <button type="button" class="team-detail-close" aria-label="关闭" @click="selected = null">×</button>
        </header>
        <div class="team-detail-total">
          <span class="label">总分</span>
          <b>{{ num(selected.total) }}</b>
        </div>
        <ul class="team-detail-cards">
          <li v-for="c in cards" :key="c">
            <span class="card-tag">{{ cardLabel(c) }}</span>
            <b>{{ num(selected.cards[c]) }}</b>
          </li>
        </ul>
        <div class="team-detail-runs">
          <div v-for="c in cards" :key="c" class="run-card-block">
            <h3>卡 {{ cardLabel(c) }}</h3>
            <table class="data-table run-table">
              <tbody>
                <tr v-for="r in runsOf.get(c) ?? []" :key="r.run_id" :class="{ dim: r.counted === false }">
                  <td class="num">{{ num(r.score) }}</td>
                  <td>{{ fmtTime(r.started_at) }}</td>
                  <td>{{ dur(r) }}</td>
                  <td>{{ statusLabel(r.status) }}<template v-if="r.reruns">（重跑 {{ r.reruns }} 次）</template><template v-if="r.counted === false">（未计入）</template><template v-else-if="selected?.best_of">（计入）</template></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="replay-slot">
          <div class="replay-picker" role="group" aria-label="选择回放卡">
            <span class="replay-picker-label">观测回放</span>
            <button
              v-for="c in cards" :key="c" type="button"
              :aria-pressed="replayCard === c" :disabled="!bestRunOf(c)"
              @click="replayCard = c"
            >{{ cardLabel(c) }}</button>
          </div>
          <div v-if="replayState === 'ready'" class="replay-stage">
            <SkyConsole :title="`${selected.name} · 卡 ${cardLabel(replayCard)} 观测回放`" />
          </div>
          <div v-else class="replay-pending">
            <p>{{ replayState === 'loading' ? '回放加载中…' : '回放生成中' }}</p>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.final-results { padding-top: 5.5rem; min-height: 100vh; background: #05060a; }
.table-wrap { margin-top: 2rem; overflow-x: auto; border: 1px solid rgba(255,255,255,.12); }
.data-table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.data-table th {
  padding: .7rem 1rem; text-align: left; font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .65rem; letter-spacing: .12em; color: #858585; border-bottom: 1px solid rgba(255,255,255,.12);
}
.data-table td { padding: .6rem 1rem; border-bottom: 1px solid rgba(255,255,255,.06); color: #d4d4d4; font-size: .9rem; }
th.r, td.r { text-align: right; }
.num { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.team-row { cursor: pointer; }
.team-row:hover td { background: rgba(120,166,255,.06); }
.name { font-weight: 500; color: #f5f5f5; }
.total { color: #f5f5f5; font-weight: 600; }
.rank { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .8rem; color: #858585; }
.rank-1 { color: #ffd76a; } .rank-2 { color: #cfd8e3; } .rank-3 { color: #d99a6c; }

.team-detail { position: fixed; inset: 0; z-index: 150; display: flex; align-items: center; justify-content: center; padding: 1.25rem; overflow-y: auto; background: rgba(3,4,8,.72); backdrop-filter: blur(6px); }
.team-detail-panel { width: 100%; max-width: 40rem; margin: auto; border: 1px solid rgba(255,255,255,.2); background: #0a0c14; box-shadow: 0 30px 80px rgba(0,0,0,.55); font-variant-numeric: tabular-nums; max-height: 90vh; overflow-y: auto; }
.team-detail-head { display: flex; align-items: center; gap: .7rem; padding: 1.1rem 1.25rem .4rem; }
.team-detail-rank { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .85rem; color: #315efb; }
.team-detail-rank.rank-1 { color: #ffd76a; } .team-detail-rank.rank-2 { color: #cfd8e3; } .team-detail-rank.rank-3 { color: #d99a6c; }
.team-detail-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 1.25rem; font-weight: 600; color: #f5f5f5; }
.team-detail-close { margin-left: auto; flex-shrink: 0; width: 2.2rem; height: 2.2rem; border: 1px solid rgba(255,255,255,.18); background: none; color: #d4d4d4; font-size: 1.3rem; line-height: 1; cursor: pointer; }
.team-detail-close:hover { border-color: #78a6ff; color: #fff; }
.team-detail-total { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin: 1rem 1.25rem 0; padding: .9rem 0; border-top: 1px solid rgba(255,255,255,.12); border-bottom: 1px solid rgba(255,255,255,.12); }
.team-detail-total .label { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .65rem; letter-spacing: .12em; color: #858585; }
.team-detail-total b { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 1.9rem; font-weight: 500; color: #f5f5f5; }
.team-detail-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; margin: 0; padding: 0; list-style: none; background: rgba(255,255,255,.12); border-bottom: 1px solid rgba(255,255,255,.12); }
.team-detail-cards li { background: #0a0c14; padding: .8rem 1.25rem; display: flex; align-items: baseline; justify-content: space-between; }
.team-detail-cards b { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-weight: 500; color: #f5f5f5; }
.card-tag { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .65rem; letter-spacing: .12em; color: #78a6ff; }
.team-detail-runs { padding: 1rem 1.25rem; }
.run-card-block h3 { margin: 1rem 0 .3rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .7rem; letter-spacing: .12em; color: #858585; font-weight: 400; }
.run-table td { padding: .35rem .5rem; font-size: .8rem; border-bottom: 1px solid rgba(255,255,255,.05); }
.run-table tr.dim td { opacity: .38; }
.replay-slot { margin: 0 1.25rem 1.25rem; }
.replay-picker { display: flex; align-items: center; gap: .4rem; margin-bottom: .6rem; }
.replay-picker-label { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .65rem; letter-spacing: .12em; color: #858585; margin-right: .3rem; }
.replay-picker button {
  min-width: 2rem; padding: 3px 10px;
  border: 1px solid rgba(255,255,255,.22); background: transparent; cursor: pointer;
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .72rem; color: rgba(255,255,255,.65);
}
.replay-picker button:hover:not(:disabled) { border-color: #315efb; color: #78a6ff; }
.replay-picker button[aria-pressed='true'] { background: rgba(49,94,251,.35); border-color: #315efb; color: #fff; }
.replay-picker button:disabled { opacity: .35; cursor: default; }
.replay-stage { border: 1px solid rgba(255,255,255,.12); }
/* Keep the embedded console compact: the stage gets a fixed height instead of its homepage aspect ratio. */
.replay-stage :deep(.sky-explainer) { display: none; }
.replay-stage :deep(.sky-console .sky-stage) { aspect-ratio: auto; height: 320px; min-height: 0; }
.replay-stage :deep(.sky-console .sky-canvas) { aspect-ratio: auto; height: 320px; min-height: 0; }
.replay-pending {
  height: 320px; display: grid; place-items: center;
  border: 1px dashed rgba(120,166,255,.35);
  color: #78a6ff; font-size: .8rem;
}
</style>
