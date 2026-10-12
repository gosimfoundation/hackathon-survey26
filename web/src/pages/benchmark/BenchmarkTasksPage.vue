<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import PageHead from '../../components/layout/PageHead.vue'
import BenchNote from './BenchNote.vue'
import { benchTasks, KITS_BASE } from '../../lib/benchmarkTasks'

const { pick } = useI18n()
const v1 = benchTasks.filter(t => t.set === 'v1')
const fresh = benchTasks.filter(t => t.set === 'new')
</script>

<template>
  <main class="poster-canvas" data-testid="benchmark-tasks">
    <PageHead :kicker="pick('AOH benchmark · tasks', 'AOH 基准 · 任务')" :title="pick('Task sets and versions', '任务集与版本')"
      :lede="pick('Every task has a version. A score is always reported together with the task and version it was earned on, so results stay comparable when tasks are improved.', '每个任务都有版本号。成绩总是和取得它的任务、版本一起报告，这样任务改进以后，旧成绩仍然可以对照。')" />
    <section class="section !pt-0"><div class="wrap">
      <BenchNote />
      <h2 class="bt-h2">{{ pick('v1 task set: Survey26', 'v1 任务集：Survey26') }}</h2>
      <div v-for="t in v1" :key="t.id" class="card bt-card">
        <span class="label accent">{{ t.id }} · {{ t.version }}</span>
        <h3>{{ pick(t.en, t.zh) }}</h3>
        <p>{{ pick(t.enDesc, t.zhDesc) }}</p>
        <p class="bt-meta">{{ pick(t.cadenceEn, t.cadenceZh) }}</p>
        <p>{{ pick('Practice cards α–δ are public. The online cards A–D and A1–D1 and the four secret final cards E–H were used in the Survey26 competition.', '练习卡 α–δ 公开；正式赛卡 A–D、A1–D1 和四张保密决赛卡 E–H 用于 Survey26 比赛。') }}
          <router-link to="/cards" class="bt-link">{{ pick('Task cards', '任务卡') }}</router-link> ·
          <router-link to="/docs" class="bt-link">{{ pick('Documentation', '文档') }}</router-link> ·
          <router-link to="/rules" class="bt-link">{{ pick('Scoring rules', '计分规则') }}</router-link></p>
      </div>

      <h2 class="bt-h2">{{ pick('New tasks (2026-10)', '新任务（2026 年 10 月）') }}</h2>
      <p class="bt-p">{{ pick('Four tasks from other parts of astroparticle physics and multi-messenger astronomy. All share one design: the numbers in the observations are not enough; the decisive information is buried in large amounts of free text (operations chat, circulars, bulletins) in English, Chinese, Japanese and Spanish, with corrections, retractions, drills and rumours. Practice and test texts are written by different authors, so keyword parsers fitted to the practice wording do not transfer. A program may call a language model through a metered interface; every call costs points.', '四道任务来自天体粒子物理和多信使天文的不同场景，共同的设计是：只看观测里的数字不够，决定性的信息藏在大量自由文字里（值班聊天、通报、公告），用英、中、日、西四种语言写成，夹杂更正、撤回、演练和传闻。练习和测试的文字由不同作者写，针对练习措辞写的关键词解析器到测试时会失效。程序可以通过计量接口调用大语言模型，每次调用都要扣分。') }}</p>
      <div v-for="t in fresh" :key="t.id" class="card bt-card">
        <span class="label accent">{{ t.id }} · {{ t.version }}</span>
        <h3>{{ pick(t.en, t.zh) }}</h3>
        <p>{{ pick(t.enDesc, t.zhDesc) }}</p>
        <p class="bt-meta">{{ pick(t.cadenceEn, t.cadenceZh) }} · {{ pick('reference baseline', '参考基线') }} {{ t.baselines[1]?.score }}</p>
        <p><a :href="KITS_BASE + 'kits/' + t.kit" class="bt-link">{{ pick('Download the public kit', '下载公开题包') }} ({{ t.kit }})</a> ·
          <a :href="KITS_BASE" class="bt-link" target="_blank" rel="noopener">{{ pick('Full task statement', '完整题目说明') }} ↗</a></p>
      </div>
    </div></section>
  </main>
</template>

<style scoped>
.bt-h2 { margin-top: 2.5rem; font-size: 1.375rem; color: #f5f5f5; }
.bt-p { margin-top: 1rem; color: #ccd4e6; line-height: 1.8; max-width: 52rem; }
.bt-card { margin-top: 1rem; }
.bt-card h3 { margin-top: .5rem; }
.bt-meta { color: #9aa5bd !important; font-size: .8rem !important; }
.bt-link { color: #78a6ff; text-decoration: underline; }
</style>
