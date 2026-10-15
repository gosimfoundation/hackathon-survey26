<script setup lang="ts">
// Sophon tab: finishers, a flag box and three boards. Every label, score and text comes from the database
// or the sophon function; this file holds no content of its own.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { supabase } from '../../lib/supabase'
import { useAuth } from '../../stores/auth'
import { fmtUtc } from '../../lib/format'

type Cell = { board: string; team_name: string; flag: string; solved_at: string; points: number; blood: number | null }
type Total = { team_name: string; debug: number; auto: number; total: number; last_at: string }
type Finisher = { board: string; team_name: string; finished_at: string; text_en: string; text_zh: string }

const { pick, locale } = useI18n()
const auth = useAuth()
const cells = ref<Cell[]>([])
const totals = ref<Total[]>([])
const finishers = ref<Finisher[]>([])
const tab = ref<'debug' | 'auto' | 'total'>('total')
const flag = ref('')
const reply = ref<string | null>(null)
const busy = ref(false)

async function load() {
  const [b, t, f] = await Promise.all([supabase.rpc('sophon_board'), supabase.rpc('sophon_totals'), supabase.rpc('sophon_finishers')])
  cells.value = !b.error && Array.isArray(b.data) ? b.data : []
  totals.value = !t.error && Array.isArray(t.data) ? t.data : []
  finishers.value = !f.error && Array.isArray(f.data) ? f.data : []
}
onMounted(load)

const boardLabel = (b: string) => b === 'auto' ? pick('Automation', '自动化榜') : b === 'debug' ? pick('Debug', '调试榜') : pick('Total', '总榜')
const columns = computed(() => [...new Set(cells.value.filter(c => c.board === tab.value).map(c => c.flag))]
  .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1))))
const rows = computed(() => {
  if (tab.value === 'total') return totals.value.map(r => ({ team: r.team_name, score: r.total, last: r.last_at, cells: {} as Record<string, Cell> }))
  const by = new Map<string, { team: string; score: number; last: string; cells: Record<string, Cell> }>()
  for (const c of cells.value.filter(x => x.board === tab.value)) {
    const r = by.get(c.team_name) ?? { team: c.team_name, score: 0, last: c.solved_at, cells: {} }
    r.score += c.points; r.cells[c.flag] = c; if (c.solved_at > r.last) r.last = c.solved_at
    by.set(c.team_name, r)
  }
  return [...by.values()].sort((a, b) => b.score - a.score || a.last.localeCompare(b.last))
})
const bloodMark = (n: number | null) => n === 1 ? pick('1st blood', '一血') : n === 2 ? pick('2nd blood', '二血') : n === 3 ? pick('3rd blood', '三血') : ''

async function submit() {
  if (!flag.value.trim()) return
  busy.value = true
  try {
    const { data, error } = await supabase.functions.invoke('sophon/desk/flag', { body: { flag: flag.value.trim() }, headers: { 'x-sophon-site': '1' } })
    const body = data ?? (error && 'context' in error ? await (error as { context: Response }).context.json().catch(() => null) : null)
    reply.value = body?.message ?? pick('No answer.', '没有回应。')
    if (body?.solved) { flag.value = ''; await load() }
  } finally { busy.value = false }
}
type Hint = { no: number; name: string; hints: string[] }
const hintList = ref<Hint[] | null>(null)
const hintNote = ref('')
async function askHint() {
  busy.value = true
  try {
    const { data, error } = await supabase.functions.invoke('sophon/desk/hint', { method: 'GET', headers: { 'x-sophon-site': '1' } })
    const body = data ?? (error && 'context' in error ? await (error as { context: Response }).context.json().catch(() => null) : null)
    hintList.value = Array.isArray(body?.hints) ? body.hints : []
    hintNote.value = body?.message ?? pick('No answer.', '没有回应。')
  } finally { busy.value = false }
}
async function download(name: string) {
  const { data } = await supabase.functions.invoke('sophon/desk/files/' + name, { method: 'GET', headers: { 'x-sophon-site': '1' } })
  if (data?.url) window.location.href = data.url
}
</script>

<template>
  <div data-testid="sophon-boards">
    <section class="card mb-8 p-4" data-testid="sophon-how-to-start">
      <p class="label mb-2">{{ pick('How to start', '怎么开始玩') }}</p>
      <ol class="list-decimal space-y-1 pl-5 text-sm">
        <li>{{ pick('Sophon is a puzzle hidden in a special task card; it does not count toward any ranking. Flags look like SOPHON{...} and are handed in in the box below.', 'Sophon 是藏在一张特别任务卡里的解谜彩蛋，不计入任何排名。flag 长这样：SOPHON{...}，在下面的框里提交。') }}</li>
        <li>{{ pick('First, look at the sky: on the Competition page switch to "Sophon" and run your agent on the Sophon card (you can practise first with the "Local card" below). Something is written in that sky; after the run the ground station checks it and leaves you a receipt, and the receipt holds a flag.', '第一步，先看天：在「参赛」页切到「Sophon」，用你的智能体跑一次 Sophon 任务卡（也可以先下载下面的「本地卡」在自己电脑上练）。这片天空里写着东西，跑完后地面站会检查你的评测并给你留一张回执，回执里就有 flag。') }}</li>
        <li>{{ pick('Then go to the front desk: create a personal API token in the Dashboard and call GET https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon/desk with the header Authorization: Bearer YOUR_TOKEN. The desk tells you which door is next, where to hand flags in and where your receipts are. Tell Johnny what the sky said and the first door opens.', '然后去前台：在「控制台」创建一个个人 API 令牌，用它访问 GET https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon/desk（请求头 Authorization: Bearer 你的令牌）。前台会告诉你下一扇门在哪、flag 交到哪、回执在哪。把天空写的话告诉 Johnny，第一扇门就开了。') }}</li>
        <li>{{ pick('From there, go door by door: each one you get through gives a flag. Stuck? Press "Ask Johnny for a hint".', '之后一扇门一扇门往里走，每过一扇门拿一个 flag。卡住了就点「向 Johnny 要提示」。') }}</li>
      </ol>
    </section>
    <section v-if="finishers.length" class="mb-8" data-testid="sophon-finishers">
      <p class="label mb-3">{{ pick('Mission log', '通关记录') }}</p>
      <article v-for="f in finishers" :key="f.board + f.team_name" class="card mb-3 p-4" data-testid="sophon-finisher">
        <p class="label text3 mb-2">{{ boardLabel(f.board) }}</p>
        <pre class="m whitespace-pre-wrap text-sm">{{ locale === 'zh' ? f.text_zh : f.text_en }}</pre>
      </article>
    </section>
    <section v-if="auth.state.session" class="mb-8" data-testid="sophon-flagbox">
      <form class="flex flex-wrap gap-2" @submit.prevent="submit">
        <input v-model="flag" class="input m flex-1" :placeholder="'SOPHON{...}'" autocomplete="off" spellcheck="false" />
        <button type="submit" class="btn" :disabled="busy">{{ pick('Hand in', '提交') }}</button>
      </form>
      <p v-if="reply" class="text2 mt-2 text-sm" data-testid="sophon-reply">{{ reply }}</p>
      <p class="mt-3 flex flex-wrap gap-3 text-sm">
        <button type="button" class="btn sm" @click="download('sophon-card-public.zip')">{{ pick('Card files', '卡片公开文件') }}</button>
        <button type="button" class="btn sm" @click="download('sophon-local.zip')">{{ pick('Local card', '本地卡') }}</button>
        <button type="button" class="btn sm" :disabled="busy" data-testid="sophon-hint-button" @click="askHint">{{ pick('Ask Johnny for a hint', '向 Johnny 要提示') }}</button>
      </p>
      <div v-if="hintList" class="card mt-3 p-4" data-testid="sophon-hints">
        <p class="text2 text-sm">{{ hintNote }}</p>
        <div v-for="h in hintList" :key="h.no" class="mt-3">
          <p class="label">#{{ h.no }} {{ h.name }}</p>
          <ol class="mt-1 list-decimal pl-5 text-sm"><li v-for="(x, i) in h.hints" :key="i">{{ x }}</li></ol>
        </div>
      </div>
    </section>
    <div class="mb-4 flex gap-2">
      <button v-for="b in (['total', 'debug', 'auto'] as const)" :key="b" type="button" class="btn sm" :class="{ primary: tab === b }" @click="tab = b">{{ boardLabel(b) }}</button>
    </div>
    <div class="table-wrap">
      <table class="data-table" data-testid="sophon-board">
        <thead>
          <tr><th>#</th><th>{{ pick('Team', '队伍') }}</th><th class="r">{{ pick('Points', '分数') }}</th>
            <template v-if="tab === 'total'"><th class="r">{{ boardLabel('debug') }}</th><th class="r">{{ boardLabel('auto') }}</th></template>
            <th v-for="c in columns" :key="c" class="r m">{{ c }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in rows" :key="r.team">
            <td class="m">{{ i + 1 }}</td><td>{{ r.team }}</td><td class="r m">{{ r.score }}</td>
            <template v-if="tab === 'total'"><td class="r m">{{ totals[i]?.debug }}</td><td class="r m">{{ totals[i]?.auto }}</td></template>
            <td v-for="c in columns" :key="c" class="r m text-xs">
              <template v-if="r.cells[c]">{{ fmtUtc(r.cells[c].solved_at) }}<br><span class="text3">{{ r.cells[c].points }}</span> <span v-if="r.cells[c].blood" class="label accent">{{ bloodMark(r.cells[c].blood) }}</span></template>
            </td>
          </tr>
          <tr v-if="!rows.length"><td :colspan="3 + columns.length" class="text3 py-8 text-center">—</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
