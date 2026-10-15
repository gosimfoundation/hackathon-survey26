<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import PageHead from '../../components/layout/PageHead.vue'
import BenchNote from './BenchNote.vue'

const { pick } = useI18n()
const analysisHref = 'https://s26-agents-8ebd56.vercel.app/analysis/'
</script>

<template>
  <main class="poster-canvas" data-testid="benchmark-survey26">
    <PageHead :kicker="pick('AOH benchmark · history', 'AOH 基准 · 历史检验')" :title="pick('Survey26: the first large stress test', 'Survey26：第一次大规模压力测试')"
      :lede="pick('In September–October 2026 the GOSIM Agentic Observer Hackathon invited teams to build agents for the v1 task set. 102 independently built systems ran under identical conditions on four secret final cards, three runs each. For the benchmark this was a stress test: it showed what the tasks reward, where the scoring could be gamed, and how reliable the ranks are.', '2026 年 9–10 月，GOSIM 智能体巡天黑客松邀请各队为 v1 任务集编写智能体。102 个独立开发的系统在四张保密决赛卡上、在完全相同的条件下各跑 3 次。对基准来说，这是一次压力测试：它显示了任务奖励什么、计分哪里能被钻空子、名次有多可靠。')" />
    <section class="section !pt-0"><div class="wrap">
      <BenchNote />
      <h2 class="bs26-h2">{{ pick('What the stress test showed', '压力测试看到了什么') }}</h2>
      <ul class="bs26-list">
        <li>{{ pick('74 of the 102 teams beat the official single-step example and 46 beat the official planning example (Python) on the final cards. The leading systems differed mainly in planning and in judging weather and faults well.', '在决赛卡上，102 支队伍中有 74 支超过官方单步示例，46 支超过官方规划示例（Python）。领先系统的差别主要在规划，以及对天气和故障的判断。') }}</li>
        <li>{{ pick('Almost every system used a large language model, but how much and where it was used did not relate to the score on these tasks.', '几乎所有系统都用了大语言模型，但用多少、用在哪里，在这些任务上和成绩没有关系。') }}</li>
        <li>{{ pick('The top ranks are reliable; in the middle of the table many neighbouring ranks are within run-to-run noise and are better read as tiers.', '前面的名次可靠；中段很多相邻名次的差距在运行间的随机波动之内，更适合按档次理解。') }}</li>
        <li>{{ pick('A scoring loophole (free false alarms) was widely used, and only four test cards were available: both are lessons for the next task versions.', '一条计分漏洞（误报的免罚次数）被广泛利用，而且测试卡只有四张：这两点都是下一版任务要改进的地方。') }}</li>
      </ul>
      <p class="bs26-small">{{ pick('Details: the independent analysis of all participating agents.', '详细内容见：全部参赛智能体的独立分析报告。') }}
        <a :href="analysisHref" target="_blank" rel="noopener" class="bs26-link">{{ pick('Analysis', '分析报告') }} ↗</a></p>

      <h2 class="bs26-h2">{{ pick('The competition, unchanged', '比赛原样保留') }}</h2>
      <div class="bs26-grid">
        <router-link to="/leaderboard/final-hidden" class="card card-lift"><h4>{{ pick('Final results', '最终结果') }}</h4><p>{{ pick('Ranks, per-card scores, replays.', '名次、逐卡成绩、回放。') }}</p></router-link>
        <router-link to="/leaderboard" class="card card-lift"><h4>{{ pick('All boards', '全部排行榜') }}</h4><p>{{ pick('Practice, online and Open Play boards.', '练习、正式赛和日常赛榜单。') }}</p></router-link>
        <router-link to="/rules" class="card card-lift"><h4>{{ pick('Rules', '规则') }}</h4><p>{{ pick('The competition rules as they were.', '比赛当时的规则。') }}</p></router-link>
        <router-link to="/about" class="card card-lift"><h4>{{ pick('Organizers', '组委会') }}</h4><p>{{ pick('Hosts, sponsors and science committee.', '主办方、赞助方和科学委员会。') }}</p></router-link>
      </div>
    </div></section>
  </main>
</template>

<style scoped>
.bs26-h2 { margin-top: 2.5rem; font-size: 1.375rem; color: #f5f5f5; }
.bs26-list { margin-top: 1rem; padding-left: 1.25rem; list-style: disc; color: #ccd4e6; line-height: 1.85; max-width: 52rem; }
.bs26-small { margin-top: 1rem; color: #9aa5bd; font-size: .875rem; line-height: 1.7; }
.bs26-link { color: #78a6ff; text-decoration: underline; }
.bs26-grid { margin-top: 1rem; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); }
.bs26-grid .card { display: block; color: inherit; }
</style>
