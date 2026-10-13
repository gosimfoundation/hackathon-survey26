<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import PageHead from '../../components/layout/PageHead.vue'
import BenchNote from './BenchNote.vue'
import { benchTasks, KITS_BASE } from '../../lib/benchmarkTasks'

const { pick } = useI18n()
const fresh = benchTasks.filter(t => t.set === 'new')
</script>

<template>
  <main class="poster-canvas" data-testid="benchmark-submit">
    <PageHead :kicker="pick('AOH benchmark · submit', 'AOH 基准 · 提交')" :title="pick('Submit any time', '随时提交')"
      :lede="pick('No season, individuals welcome, any subset of tasks, one run per submission.', '不限赛期、个人可参加、任务任选、每次提交跑一次即可。')" />
    <section class="section !pt-0"><div class="wrap">
      <BenchNote />
      <div class="bs-grid">
        <div class="card">
          <span class="label accent">{{ pick('v1 task set · open now', 'v1 任务集 · 现在可用') }}</span>
          <h3>{{ pick('Survey26 tasks in Open Play', '在"日常赛"提交 Survey26 任务') }}</h3>
          <p>{{ pick('Open Play runs on the same cards as the online competition (A–D and A1–D1). It has its own board, no prizes, and never changes the competition results. Sign in and open the workspace.', '日常赛使用正式赛的任务卡（A–D 与 A1–D1），有自己的排行榜，不设奖项，也不会改变比赛结果。登录后进入工作台即可。') }}</p>
          <p class="bs-actions"><router-link to="/compete" class="btn primary">{{ pick('Open the workspace', '进入工作台') }}</router-link>
            <router-link to="/start" class="btn">{{ pick('Getting started', '入门') }}</router-link></p>
        </div>
        <div class="card">
          <span class="label accent">{{ pick('New tasks · channel in preparation', '新任务 · 提交通道准备中') }}</span>
          <h3>{{ pick('Practise locally today', '现在可以先在本地练习') }}</h3>
          <p>{{ pick('Download a kit, write agent.py (Python standard library only), and score it on the public practice seeds 0–9 with the included runner. Official scores use secret seeds and secret texts that stay on the server; the online channel will accept one run per submission and any subset of the four tasks.', '下载题包，写一个 agent.py（只用 Python 标准库），用题包自带的运行器在公开练习种子 0–9 上打分。正式成绩使用保存在服务器端的保密种子和保密文字；线上通道开通后，每次提交跑一次即可，四道题任选。') }}</p>
          <ul class="bs-list">
            <li v-for="t in fresh" :key="t.id"><a :href="KITS_BASE + 'kits/' + t.kit" class="bs-link">{{ pick(t.en, t.zh) }} · {{ t.kit }}</a></li>
          </ul>
          <p class="bs-code">python3 -m aohkit.runner --problem nu_followup_v5 --seed 0 --agent "python3 agent.py"</p>
        </div>
      </div>
    </div></section>
  </main>
</template>

<style scoped>
.bs-grid { margin-top: 1.5rem; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }
.bs-grid h3 { margin-top: .5rem; }
.bs-actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem !important; }
.bs-list { margin-top: .75rem; padding-left: 1.25rem; list-style: disc; color: #ccd4e6; line-height: 1.9; font-size: .9rem; }
.bs-link { color: #78a6ff; text-decoration: underline; }
.bs-code { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .75rem !important; overflow-x: auto; white-space: nowrap; background: rgba(0,0,0,.35); padding: .5rem .75rem; }
</style>
