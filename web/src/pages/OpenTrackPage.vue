<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../composables/useI18n'
import { useAuth } from '../stores/auth'
import PageHead from '../components/layout/PageHead.vue'
import {
  DAILY_LIMIT, PENDING_LIMIT, cancel, executorKey, explain, leaderboard, listProblems, modelProblem, mySubmissions, submit, zipProblem,
  type OpenBoardRow, type OpenProblem, type OpenScore, type OpenSubmission,
} from '../lib/openTrack'

const { pick } = useI18n()
const { isLoggedIn } = useAuth()
const base = import.meta.env.BASE_URL

const problems = ref<OpenProblem[]>([])
const board = ref<OpenBoardRow[]>([])
const subs = ref<OpenSubmission[]>([])
const scores = ref<OpenScore[]>([])
const jwk = ref<JsonWebKey | null>(executorKey)
const chosen = ref<string[]>([])
const file = ref<Uint8Array | null>(null)
const fileName = ref('')
const useModel = ref(false)
const model = ref({ base: 'https://', model: '', key: '' })
const busy = ref(false)
const message = ref<{ en: string; zh: string } | null>(null)
const loadError = ref('')

const title = (id: string) => {
  const p = problems.value.find(x => x.id === id)
  return p ? pick(p.title_en, p.title_zh) : id
}
const boardBy = computed(() => problems.value.map(p => ({ p, rows: board.value.filter(r => r.problem_id === p.id) })))
const scoreOf = (sid: string, pid: string) => scores.value.find(s => s.submission_id === sid && s.problem_id === pid)
const fmt = (x: number | null | undefined) => (x == null ? '—' : x.toFixed(1))
const statusText: Record<string, [string, string]> = {
  queued: ['Queued', '排队中'], running: ['Running', '运行中'], done: ['Finished', '已完成'], failed: ['Failed', '失败'], cancelled: ['Cancelled', '已取消'],
}

async function refresh() {
  try {
    problems.value = await listProblems()
    board.value = await leaderboard()
    if (isLoggedIn.value) ({ subs: subs.value, scores: scores.value } = await mySubmissions())
  } catch (e) {
    loadError.value = String((e as Error)?.message ?? e)
  }
}

async function pickFile(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0]
  message.value = null
  file.value = null
  fileName.value = f?.name ?? ''
  if (!f) return
  const bytes = new Uint8Array(await f.arrayBuffer())
  const bad = zipProblem(bytes)
  if (bad) {
    message.value = bad === 'too_large' ? { en: 'The ZIP is larger than 2 MB.', zh: 'ZIP 超过 2 MB。' } : { en: 'Please choose a ZIP file.', zh: '请选择 ZIP 文件。' }
    return
  }
  file.value = bytes
}

async function send() {
  message.value = null
  if (!chosen.value.length) { message.value = { en: 'Choose at least one task.', zh: '请至少选一道题。' }; return }
  if (!file.value) { message.value = { en: 'Choose your agent ZIP.', zh: '请选择你的 agent ZIP。' }; return }
  const m = useModel.value ? { ...model.value } : null
  const badModel = modelProblem(m)
  if (badModel) { message.value = { en: 'Model API: an https base URL, a model name and a key are needed.', zh: '模型接口需要 https 地址、模型名和密钥。' }; return }
  busy.value = true
  try {
    await submit(chosen.value, file.value, m, jwk.value)
    model.value.key = ''
    message.value = { en: 'Submitted. Each chosen task runs once on its hidden seeds; results appear below.', zh: '已提交。每道选中的题在保密种子上各跑一次，结果会显示在下方。' }
    await refresh()
  } catch (e) {
    message.value = explain(e)
  } finally {
    busy.value = false
  }
}

async function stop(id: string) {
  try { await cancel(id); await refresh() } catch (e) { message.value = explain(e) }
}

onMounted(async () => {
  await refresh()
})
</script>

<template>
  <main class="poster-canvas" data-testid="open-track">
    <PageHead :kicker="pick('AOH benchmark · open track', 'AOH 基准 · 开放赛道')" :title="pick('Four new tasks, open for submission', '四道新题，开放提交')"
      :lede="pick('Individuals welcome, any subset of the tasks, one run per submission, no season.', '个人即可参加，题目任选，每次提交跑一次，不限赛期。')" />

    <section class="section !pt-0"><div class="wrap">
      <div class="card ot-rules">
        <span class="label accent">{{ pick('Rules', '规则') }}</span>
        <ul>
          <li>{{ pick('Sign in and submit on your own; no team is needed.', '登录后个人提交，不需要组队。') }}</li>
          <li>{{ pick('Choose any of the four tasks for a submission; each chosen task runs once (no three-run average).', '每次提交可以只选其中几道题；每道题只跑一次，不再取三次平均。') }}</li>
          <li>{{ pick('A task\'s score is the mean over its fixed hidden seeds. The board keeps each participant\'s best submission per task.', '每道题的成绩是它固定的几组保密种子上的平均分；排行榜取每人每题最好的一次。') }}</li>
          <li>{{ pick(`Upload a ZIP with agent.py at its root (Python standard library only, at most 2 MB). Up to ${DAILY_LIMIT} submissions a day, ${PENDING_LIMIT} waiting at once.`, `上传 ZIP，根目录放 agent.py（只用 Python 标准库，不超过 2 MB）。每天最多 ${DAILY_LIMIT} 次，同时排队最多 ${PENDING_LIMIT} 个。`) }}</li>
          <li>{{ pick('Your agent runs with no network. aohkit.llm.ask works only if you add your own model API; every call is metered and its cost is part of the score. Your key is encrypted in this page and only the evaluation machine can read it.', '你的程序运行时没有网络。只有填写了自己的模型接口，aohkit.llm.ask 才可用；每次调用都会计量，费用计入成绩。密钥在本页加密，只有评测机器能解开。') }}</li>
          <li>{{ pick('This track has its own board and never changes the Survey26 competition results.', '本赛道有自己的排行榜，不会改变 Survey26 比赛的结果。') }}</li>
        </ul>
      </div>

      <div class="ot-grid">
        <div v-for="p in problems" :key="p.id" class="card">
          <span class="label">{{ p.id }}</span>
          <h3>{{ pick(p.title_en, p.title_zh) }}</h3>
          <p class="ot-dim">{{ pick(`${p.seed_indices.length} hidden seeds per run`, `每次运行 ${p.seed_indices.length} 组保密种子`) }}</p>
          <p><a :href="base + p.kit_url" class="ot-link">{{ pick('Download the kit', '下载题包') }}</a></p>
        </div>
      </div>

      <div class="card ot-submit">
        <span class="label accent">{{ pick('Submit', '提交') }}</span>
        <p v-if="!isLoggedIn">{{ pick('Sign in to submit.', '登录后即可提交。') }} <router-link to="/register?mode=login" class="btn primary">{{ pick('Sign in', '登录') }}</router-link></p>
        <form v-else @submit.prevent="send">
          <fieldset class="ot-tasks">
            <label v-for="p in problems" :key="p.id"><input v-model="chosen" type="checkbox" :value="p.id" /> {{ pick(p.title_en, p.title_zh) }}</label>
          </fieldset>
          <p><input type="file" accept=".zip,application/zip" data-testid="open-zip" @change="pickFile" /> <span class="ot-dim">{{ fileName }}</span></p>
          <p><label><input v-model="useModel" type="checkbox" :disabled="!jwk" /> {{ pick('Use my own model API (OpenAI-compatible)', '使用我自己的模型接口（OpenAI 兼容）') }}</label>
            <span v-if="!jwk" class="ot-dim"> · {{ pick('not open yet', '暂未开放') }}</span></p>
          <div v-if="useModel" class="ot-model">
            <input v-model="model.base" placeholder="https://api.example.com/v1" autocomplete="off" />
            <input v-model="model.model" :placeholder="pick('model name', '模型名')" autocomplete="off" />
            <input v-model="model.key" type="password" :placeholder="pick('API key', 'API 密钥')" autocomplete="off" />
          </div>
          <p><button class="btn primary" :disabled="busy" type="submit">{{ busy ? pick('Submitting…', '提交中…') : pick('Submit', '提交') }}</button></p>
        </form>
        <p v-if="message" class="ot-msg">{{ pick(message.en, message.zh) }}</p>
      </div>

      <div v-if="isLoggedIn && subs.length" class="card">
        <span class="label accent">{{ pick('My submissions', '我的提交') }}</span>
        <table class="ot-table">
          <thead><tr><th>{{ pick('Time', '时间') }}</th><th>{{ pick('Status', '状态') }}</th><th>{{ pick('Tasks and scores', '题目与成绩') }}</th><th>{{ pick('Model', '模型') }}</th><th></th></tr></thead>
          <tbody>
            <tr v-for="s in subs" :key="s.id">
              <td>{{ new Date(s.created_at).toLocaleString() }}</td>
              <td>{{ pick(...(statusText[s.status] ?? [s.status, s.status])) }}</td>
              <td><div v-for="pid in s.problems" :key="pid">{{ title(pid) }}: <b>{{ fmt(scoreOf(s.id, pid)?.mean_total) }}</b>
                <span class="ot-dim">({{ scoreOf(s.id, pid)?.seeds_done ?? 0 }}/{{ scoreOf(s.id, pid)?.seeds ?? '?' }})</span></div></td>
              <td>{{ s.uses_model ? `${s.model_name} …${s.key_hint}` : pick('none', '无') }}</td>
              <td><button v-if="s.status === 'queued'" class="btn" @click="stop(s.id)">{{ pick('Cancel', '取消') }}</button></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <span class="label accent">{{ pick('Leaderboard', '排行榜') }}</span>
        <p v-if="loadError" class="ot-msg">{{ loadError }}</p>
        <div v-for="b in boardBy" :key="b.p.id" class="ot-board">
          <h3>{{ pick(b.p.title_en, b.p.title_zh) }}</h3>
          <p v-if="!b.rows.length" class="ot-dim">{{ pick('No finished submissions yet.', '还没有完成的提交。') }}</p>
          <table v-else class="ot-table">
            <thead><tr><th>#</th><th>{{ pick('Participant', '参赛者') }}</th><th>{{ pick('Best mean score', '最好平均分') }}</th><th>{{ pick('Model', '模型') }}</th><th>{{ pick('Submissions', '提交次数') }}</th></tr></thead>
            <tbody><tr v-for="(r, i) in b.rows" :key="r.player"><td>{{ i + 1 }}</td><td>{{ r.player }}</td><td>{{ fmt(r.best_total) }}</td>
              <td>{{ r.uses_model ? pick('yes', '有') : pick('no', '无') }}</td><td>{{ r.submissions }}</td></tr></tbody>
          </table>
        </div>
      </div>
    </div></section>
  </main>
</template>

<style scoped>
.ot-rules ul { margin-top: .75rem; padding-left: 1.25rem; list-style: disc; line-height: 1.9; color: #ccd4e6; }
.ot-grid { margin: 1rem 0; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); }
.ot-grid h3 { margin-top: .5rem; }
.ot-submit, .ot-board { margin-bottom: 1rem; }
.ot-tasks { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; margin: .75rem 0; border: 0; padding: 0; }
.ot-model { display: grid; gap: .5rem; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); margin-bottom: .75rem; }
.ot-model input { background: rgba(0,0,0,.35); border: 1px solid #2c3a5c; padding: .4rem .6rem; color: inherit; min-width: 0; }
.ot-link { color: #78a6ff; text-decoration: underline; }
.ot-dim { color: #8b97b3; font-size: .85rem; }
.ot-msg { margin-top: .75rem; color: #ffd27a; }
.ot-table { width: 100%; border-collapse: collapse; font-size: .85rem; display: block; overflow-x: auto; }
.ot-table th, .ot-table td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #22304d; vertical-align: top; }
.card { margin-top: 1rem; }
</style>
