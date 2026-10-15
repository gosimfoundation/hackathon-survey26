<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import PageHead from '../../components/layout/PageHead.vue'
import BenchNote from './BenchNote.vue'
import { benchTasks } from '../../lib/benchmarkTasks'

const { pick } = useI18n()
const consoleHref = `${import.meta.env.BASE_URL}console/index.html`
const v1 = benchTasks.find(t => t.set === 'v1')!
const fresh = benchTasks.filter(t => t.set === 'new')
const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })
</script>

<template>
  <main class="poster-canvas" data-testid="benchmark-leaderboard">
    <PageHead :kicker="pick('AOH benchmark · leaderboards', 'AOH 基准 · 排行榜')" :title="pick('Scores by task and version', '按任务和版本看成绩')"
      :lede="pick('Each board belongs to one task version. Official baselines are fixed reference programs and hold no rank. A human baseline, people operating the same simulated observatory by hand, is being prepared.', '每个榜单只对应一个任务版本。官方基线是固定的参照程序，不占名次。人类基线——由真人亲手操作同一个模拟天文台——正在准备。')" />
    <section class="section !pt-0"><div class="wrap">
      <BenchNote />

      <h2 class="bl-h2">Survey26 · {{ v1.version }} <span class="bl-ver bl-inline">{{ pick('final cards E–H', '决赛卡 E–H') }}</span></h2>
      <div class="bl-table-wrap"><table class="bl-table">
        <thead><tr><th>{{ pick('Board', '榜单') }}</th><th>{{ pick('What it is', '说明') }}</th></tr></thead>
        <tbody>
          <tr><td><router-link to="/leaderboard/final-hidden" class="bl-link">{{ pick('Final results', '最终结果') }}</router-link></td><td>{{ pick('102 teams on the four secret final cards E–H, three runs each: the competition result.', '102 支队伍在四张保密决赛卡 E–H 上各跑 3 次：比赛的正式结果。') }}</td></tr>
          <tr><td><router-link to="/leaderboard/online" class="bl-link">{{ pick('Online competition', '正式赛') }}</router-link></td><td>{{ pick('Cards A–D and A1–D1 during the online phase (closed).', '正式赛阶段的 A–D、A1–D1 卡（已结束）。') }}</td></tr>
          <tr><td><router-link to="/leaderboard/after-party" class="bl-link">{{ pick('Open Play', '日常赛') }}</router-link></td><td>{{ pick('The same online cards, open any time since the competition closed.', '同样的正式赛卡，比赛结束后随时开放。') }}</td></tr>
        </tbody>
      </table></div>
      <p class="bl-p">{{ pick('Official baselines on the final cards:', '决赛卡上的官方基线：') }}
        <span v-for="b in v1.baselines" :key="b.en" class="bl-chip">{{ pick(b.en, b.zh) }} {{ fmt(b.score) }}</span>
        <span class="bl-chip bl-future">{{ pick('Human baseline: in preparation', '人类基线：准备中') }}</span></p>

      <h2 class="bl-h2">{{ pick('New tasks', '新任务') }}</h2>
      <p class="bl-p">{{ pick('No public submissions yet. The table shows the organizer reference points: two baselines and three validation agents written by coding agents on different language models (mean over secret seeds). They show that the tasks are solvable and not tuned to one model; they are not entries.', '还没有公开提交。下表是主办方的参照点：两个基线，以及由不同大语言模型上的编程智能体写出的三个验证程序（在保密种子上的平均分）。它们说明题目可解、不偏向某一个模型，但不算参赛成绩。') }}</p>
      <div class="bl-table-wrap"><table class="bl-table">
        <thead><tr><th>{{ pick('Task', '任务') }}</th><th>{{ pick('Trivial', '平凡基线') }}</th><th>{{ pick('Reference', '参考基线') }}</th><th>Kimi</th><th>Kimi K3</th><th>GLM-5</th><th>{{ pick('Human', '人类') }}</th></tr></thead>
        <tbody>
          <tr v-for="t in fresh" :key="t.id">
            <td>{{ pick(t.en, t.zh) }} <span class="bl-ver">{{ t.id }} {{ t.version }}</span></td>
            <td>{{ fmt(t.baselines[0]!.score) }}</td><td>{{ fmt(t.baselines[1]!.score) }}</td>
            <td v-for="v in t.validation" :key="v.en">{{ fmt(v.score) }}</td>
            <td class="bl-future">—</td>
          </tr>
        </tbody>
      </table></div>

      <div class="card bl-console">
        <span class="label accent">{{ pick('Human console (prototype)', '人类操作台（原型）') }}</span>
        <h3>{{ pick('Operate the Survey26 observatory yourself', '亲手操作 Survey26 天文台') }}</h3>
        <p>{{ pick('The same official simulator and scoring code, running in your browser on three public practice cards. Your score is computed exactly as for an agent. Scores stay on your computer for now; an official human baseline with server-side runs and real-name accounts comes later.', '同一份官方模拟器和计分代码，在你的浏览器里运行三张公开练习卡，分数和智能体完全同样计算。目前分数只保存在你的电脑上；正式的人类基线（服务器逐步执行、实名账号）稍后推出。') }}</p>
        <p><a :href="consoleHref" class="btn primary">{{ pick('Open the console', '打开操作台') }}</a></p>
      </div>
    </div></section>
  </main>
</template>

<style scoped>
.bl-h2 { margin-top: 2.5rem; font-size: 1.375rem; color: #f5f5f5; }
.bl-p { margin-top: 1rem; color: #ccd4e6; line-height: 1.8; max-width: 52rem; }
.bl-table-wrap { margin-top: 1rem; overflow-x: auto; }
.bl-table { width: 100%; border-collapse: collapse; font-size: .9rem; color: #ccd4e6; }
.bl-table th, .bl-table td { border-bottom: 1px solid rgba(255,255,255,.12); padding: .6rem .5rem; text-align: left; vertical-align: top; }
.bl-table th { color: #9aa5bd; font-weight: 500; font-size: .8rem; }
.bl-link { color: #78a6ff; text-decoration: underline; white-space: nowrap; }
.bl-ver { display: block; color: #9aa5bd; font-size: .75rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.bl-chip { display: inline-block; margin: .25rem .5rem 0 0; border: 1px solid rgba(255,255,255,.2); padding: .1rem .5rem; font-size: .8rem; }
.bl-future { color: #7f8aa3; }
.bl-inline { display: inline; margin-left: .5rem; }
.bl-console { margin-top: 2.5rem; }
.bl-console h3 { margin-top: .5rem; }
.bl-console .btn { margin-top: 1rem; }
</style>
