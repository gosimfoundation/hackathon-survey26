<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import PageHead from '../../components/layout/PageHead.vue'
import BenchNote from './BenchNote.vue'
import { benchTasks } from '../../lib/benchmarkTasks'

const { pick } = useI18n()
const consoleHref = `${import.meta.env.BASE_URL}console/index.html`

const scoring = [
  { en: 'Science value of the observations', zh: '观测本身的科学收益', enD: 'each finished exposure earns points by target value, weighted by the actual sky conditions and image quality at that moment', zhD: '每次完成的曝光按目标价值得分，并按当时真实的天气、成像质量折算' },
  { en: 'Must-observe targets', zh: '必观测目标', enD: 'targets marked REQUIRED cost points if they are never observed', zhD: '标为"必需"的目标如果始终没拍到，要扣分' },
  { en: 'Instrument faults', zh: '设备故障', enD: 'noticing a hidden fault from the data and reporting it starts a repair; false alarms beyond a small allowance cost points', zhD: '从数据里察觉隐藏的设备故障并上报，就会安排维修；超出少量免罚次数的误报要扣分' },
  { en: 'Urgent observation requests', zh: '临时观测请求', enD: 'requests that arrive during the run (e.g. a transient to follow up) earn points if visited in time', zhD: '运行中途到来的请求（比如追踪一个暂现源）及时去拍就得分' },
  { en: 'Even coverage', zh: '覆盖均匀', enD: 'a bonus for spreading finished work across the survey regions instead of abandoning some', zhD: '完成的观测在各个天区分布均匀有加分，避免为了分数整片放弃某些天区' },
]
const protocol = [
  { en: 'Secret test tasks', zh: '保密测试任务', enD: 'the cards that decide the score are not seen by anyone in advance', zhD: '决定成绩的任务卡事先谁都看不到' },
  { en: 'Identical conditions', zh: '条件完全相同', enD: 'every system faces the same weather, faults and request sequence', zhD: '每个系统面对同样的天气、故障和请求序列' },
  { en: 'Repeated runs', zh: '多次运行', enD: 'each task is run several times to measure stability', zhD: '每个任务跑多次，看结果稳不稳' },
  { en: 'Archived and replayable', zh: '存档、可回放', enD: 'every action and score is stored and can be re-scored and replayed', zhD: '每一步动作和分数都存档，可以重新计分、动画回放' },
  { en: 'Official baselines', zh: '官方基线', enD: 'organizer example programs run alongside as fixed reference points', zhD: '主办方的示例程序一起跑，作为固定参照' },
  { en: 'Are the ranks real?', zh: '名次是否分得开', enD: 'statistics check which rank differences are larger than run-to-run noise', zhD: '用统计方法检查哪些名次差距大于运行间的随机波动' },
]
</script>

<template>
  <main class="poster-canvas bench" data-testid="benchmark-home">
    <PageHead :kicker="pick('AOH · benchmark view (trial)', 'AOH · 基准视图（试用）')"
      :title="pick('A benchmark for autonomous survey operations', '自主巡天运行的公共基准')"
      :lede="pick(
        'Modern sky surveys make thousands of operational decisions every night: where to point, what to observe, how to react to weather, faults and alerts. These decisions are increasingly left to software, but there is no shared yardstick to compare such systems. AOH (Agentic Observer Hackathon) is a step towards one: a simulated observatory where any program, rule-based, optimisation, machine learning or LLM agent, is scored under identical conditions.',
        '现代巡天每晚要做上千个运行决策：望远镜指向哪里、拍什么、遇到天气变化、设备故障和突发警报怎么办。这些决策越来越多地交给程序，但还没有一把公共的尺子来比较这些程序。AOH（智能体巡天）是朝这个方向迈出的一步：一个模拟天文台，任何程序——规则、优化、机器学习还是大语言模型智能体——都在完全相同的条件下打分。')" />
    <section class="section !pt-0"><div class="wrap">
      <BenchNote />
      <p class="bench-p">{{ pick('The Survey26 hackathon (2026) was the means, not the goal: more than a hundred teams built systems for the same tasks, which made it the first large stress test of the benchmark. Its results are kept unchanged on the', 'Survey26 黑客松（2026 年）是手段而不是目的：一百多支队伍为同样的任务写系统，它成了这个基准的第一次大规模压力测试。比赛结果原样保留在') }} <router-link to="/benchmark/survey26">{{ pick('Survey26 page', 'Survey26 检验页') }}</router-link>.</p>

      <h2 class="bench-h2">{{ pick('What the benchmark measures', '基准测什么') }}</h2>
      <div class="bench-grid3">
        <div class="card"><span class="label accent">{{ pick('Task', '任务') }}</span>
          <p>{{ pick('Run an observatory, or a detector network, for days to weeks with incomplete information, making a decision at every step (every 10 minutes to every 6 hours). A step is an action such as point and expose, wait, raise an alert or report a fault. Nothing is graded by hand: the score is computed automatically.', '在信息不完整的情况下，连续几天到几周运行一台望远镜或一套探测器网络，每一步（10 分钟到 6 小时一次）都要做决定。一步就是一个动作，比如指向并曝光、等待、发警报、上报故障。没有人工阅卷，分数自动算出。') }}</p></div>
        <div class="card"><span class="label accent">{{ pick('Data (the tasks themselves)', '数据（题目）') }}</span>
          <p>{{ pick('Public practice tasks for development, and secret test tasks for scoring. Tasks are simulated: weather, faults and alerts come from generators with known truth, and the new tasks add large amounts of free text in four languages, written by different authors for practice and test.', '公开的练习任务用来开发，保密的测试任务用来计分。任务是模拟生成的：天气、故障、警报都来自真值已知的生成器；新任务还加入了大量四种语言的自由文字，练习和测试的文字由不同作者写。') }}</p></div>
        <div class="card"><span class="label accent">{{ pick('Evaluation (a whole system, not one rule)', '评测（一整套体系，不是一条规则）') }}</span>
          <p>{{ pick('A score with several parts plus a protocol that makes scores comparable and checkable, listed below.', '由几个部分组成的分数，加上一套让分数可比、可核查的评测流程，见下。') }}</p></div>
      </div>

      <h3 class="bench-h3">{{ pick('The score (Survey26 v1 task set: five parts)', '分数怎么算（Survey26 v1 任务集：五个方面）') }}</h3>
      <ol class="bench-list">
        <li v-for="s in scoring" :key="s.en"><b>{{ pick(s.en, s.zh) }}</b>：{{ pick(s.enD, s.zhD) }}</li>
      </ol>
      <p class="bench-small">{{ pick('Each new task has its own score of the same kind (rewards for timely correct actions, penalties for false claims and missed events, and a metered cost for every LLM call); see its task page.', '每道新任务也有同类型的计分（及时、正确的动作得分，误报和漏报扣分，每次调用大语言模型按用量扣分），详见任务页。') }}</p>

      <h3 class="bench-h3">{{ pick('The protocol', '评测流程') }}</h3>
      <div class="bench-grid3">
        <div v-for="p in protocol" :key="p.en" class="card"><h4>{{ pick(p.en, p.zh) }}</h4><p>{{ pick(p.enD, p.zhD) }}</p></div>
      </div>

      <h2 class="bench-h2">{{ pick('Tasks', '任务') }}</h2>
      <div class="bench-tasks">
        <router-link v-for="t in benchTasks" :key="t.id" to="/benchmark/tasks" class="card card-lift bench-task">
          <span class="label">{{ t.set === 'v1' ? pick('v1 task set', 'v1 任务集') : pick('new task', '新任务') }} · {{ t.id }} {{ t.version }}</span>
          <h4>{{ pick(t.en, t.zh) }}</h4>
          <p>{{ pick(t.cadenceEn, t.cadenceZh) }}</p>
        </router-link>
      </div>

      <h2 class="bench-h2">{{ pick('Take part any time', '随时参加') }}</h2>
      <p class="bench-p">{{ pick('The benchmark is meant to stay open after the competition. The rules of the open track:', '基准在比赛结束后继续开放。开放赛道的规则：') }}</p>
      <ul class="bench-list">
        <li>{{ pick('No season: submissions are open all year.', '不限赛期：全年开放提交。') }}</li>
        <li>{{ pick('Individuals are welcome; no team needed.', '个人即可参加，不需要组队。') }}</li>
        <li>{{ pick('Do one task or several; you do not have to do them all.', '可以只做一道或几道任务，不必全做。') }}</li>
        <li>{{ pick('One run per submission is enough to get a score.', '每次提交跑一次就能得到成绩。') }}</li>
      </ul>
      <p class="bench-small">{{ pick('Status today: the v1 tasks can be submitted in Open Play on the competition workspace; the online submission channel for the new tasks is being prepared, and their public kits can already be downloaded for local practice.', '目前的状态：v1 任务可以在比赛工作台的"日常赛"里提交；新任务的线上提交通道正在准备，公开题包已经可以下载、在本地练习。') }}</p>
      <div class="bench-actions">
        <router-link to="/benchmark/submit" class="btn primary">{{ pick('How to submit', '怎么提交') }}</router-link>
        <router-link to="/benchmark/leaderboard" class="btn">{{ pick('Leaderboards', '排行榜') }}</router-link>
        <a :href="consoleHref" class="btn">{{ pick('Try it yourself: human console', '亲自上手：人类操作台') }}</a>
      </div>

      <h2 class="bench-h2">{{ pick('How to cite', '引用方式') }}</h2>
      <p class="bench-p">{{ pick('A paper describing the benchmark is in preparation. Until it is out, please cite it as: “AOH: Agentic Observer Hackathon, a step towards a benchmark for autonomous astronomical survey operations (2026)”.', '介绍这个基准的论文正在撰写中。论文发表前，请这样引用："AOH: Agentic Observer Hackathon, a step towards a benchmark for autonomous astronomical survey operations (2026)"。') }}</p>
    </div></section>
  </main>
</template>

<style scoped>
.bench-p { margin-top: 1.25rem; color: #ccd4e6; line-height: 1.8; max-width: 52rem; }
.bench-p a, .bench-small a { color: #78a6ff; text-decoration: underline; }
.bench-h2 { margin-top: 3rem; font-size: 1.5rem; color: #f5f5f5; letter-spacing: -.02em; }
.bench-h3 { margin-top: 2rem; font-size: 1.125rem; color: #f5f5f5; }
.bench-small { margin-top: .75rem; color: #9aa5bd; font-size: .875rem; line-height: 1.7; max-width: 52rem; }
.bench-grid3 { margin-top: 1rem; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
.bench-tasks { margin-top: 1rem; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); }
.bench-task { display: block; color: inherit; }
.bench-task h4 { margin-top: .5rem; }
.bench-list { margin-top: 1rem; padding-left: 1.25rem; color: #ccd4e6; line-height: 1.85; max-width: 52rem; list-style: disc; }
ol.bench-list { list-style: decimal; }
.bench-list b { color: #f5f5f5; font-weight: 500; }
.bench-actions { margin-top: 1.5rem; display: flex; flex-wrap: wrap; gap: .75rem; }
</style>
