<script setup lang="ts">
import { useScrollReveal } from '../composables/useScrollReveal'
useScrollReveal()
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../composables/useI18n'
import { appUrl } from '../composables/api'
import { isSupabaseConfigured } from '../lib/supabase'
import { loadPhases, SCENARIO_FILES, scenarioFileVisible, type Scenario, type ScenarioFile, type ScenarioFileGroup } from '../lib/data'
import { downloadObject } from '../lib/storage'
import { useFlash } from '../stores/flash'
import { competition } from '../stores/competition'
import PageHead from '../components/layout/PageHead.vue'
import { useQuestFlags } from '../composables/useQuestFlags'

const { t } = useI18n()
const flash = useFlash()
// A signed-in download counts as the dashboard quest's kit step.
const { remember } = useQuestFlags()
const scenarios = ref<Scenario[]>([])
const loading = ref(true)
const busy = ref<string | null>(null)
const GROUPS: ScenarioFileGroup[] = ['config', 'data', 'weather', 'forecasts', 'events']

const kit = computed(() => [
  { n: '01', title: 'resources.kit', desc: 'resources.kit_desc', href: appUrl('/downloads/agent-observer-starter-kit.zip'), primary: true, label: 'common.download' },
  { n: '02', title: 'resources.reference', desc: 'resources.reference_desc', href: 'https://github.com/BH3GEI/observer-project-example', primary: false, label: 'common.view', view: true },
  { n: '03', title: 'resources.scorer', desc: 'resources.scorer_desc', href: appUrl('/downloads/scoring_core.py'), primary: false, label: 'common.download' },
  { n: '04', title: 'resources.skill', desc: 'resources.skill_desc', href: appUrl('/skill.md'), primary: false, label: 'common.view', view: true },
  { n: '05', title: 'resources.docs', desc: 'resources.docs_desc', href: '/docs', primary: false, label: 'common.view', route: true },
])
const cli = `# environment for sac_submit.py (also printed in SKILL.md inside the kit)
export SAC_URL=${import.meta.env.VITE_SUPABASE_URL || 'https://<ref>.supabase.co'}
export SAC_KEY=${import.meta.env.VITE_SUPABASE_ANON_KEY || '<anon key>'}
export SAC_EMAIL=you@example.org SAC_PASSWORD='...'

unzip agent-observer-starter-kit.zip && cd agent-observer-starter-kit
# run the minimal agent locally on the bundled public scenario, then re-score the trace (details: SKILL.md)
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 600 --out run_output
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_output/decisions.csv
python3 make_scenario.py --out scenarios/mine --seed 7 --days 30      # more practice scenarios
python3 fetch_scenario.py dev-fortnight                                # any published scenario -> scenarios/dev-fortnight/
# submit the decisions.csv your local run produced
python3 sac_submit.py --phase practice --kind results --scenario dev-reference --file run_output/decisions.csv --wait`
const filesFor = (group: ScenarioFileGroup) => SCENARIO_FILES.filter(f => f.group === group)
const groupVisible = (s: Scenario, group: ScenarioFileGroup) => filesFor(group).some(f => scenarioFileVisible(s, f))
const fmtClock = (v: number | null | undefined) => v == null ? '—' : v >= 3600 ? `${(v / 3600).toFixed(v % 3600 ? 1 : 0)} h` : `${Math.round(v / 60)} min`
const active = computed(() => scenarios.value.filter(s => s.is_active))

async function download(scenario: Scenario, file: ScenarioFile) {
  const key = `${scenario.slug}/${file.key}`
  busy.value = key
  try { await downloadObject('scenarios', key, `${scenario.slug}-${file.name}`) }
  catch { flash.error(t('subs.download_failed')) }
  finally { busy.value = null }
}

onMounted(async () => {
  try { scenarios.value = isSupabaseConfigured ? (await loadPhases()).flatMap(p=>p.scenarios) : [] }
  catch { scenarios.value = [] }
  finally { loading.value = false }
})
</script>

<template>
  <main class="poster-canvas">
    <PageHead :kicker="t('resources.kicker')" :title="t('resources.title')" :lede="t('resources.lede')" />
    <section class="section"><div class="wrap">
      <div class="flow-band reveal">
        <div class="flow-head"><span class="flow-step">1</span><div><h2>{{ t('resources.flow1') }}</h2><p>{{ t('resources.flow1_hint') }}</p></div></div>
        <div class="cards cards-1">
          <article v-tilt class="card card-lift flow-primary">
            <span class="label accent">{{ kit[0].n }}</span>
            <h3 class="mt-3">{{ t(kit[0].title) }}</h3>
            <p>{{ t(kit[0].desc) }}</p>
            <p class="mt-5"><a class="btn primary" :href="kit[0].href" download @click="remember('prepare')">{{ t(kit[0].label) }} ↓</a></p>
          </article>
        </div>
      </div>

      <div class="flow-band reveal mt-16">
        <div class="flow-head"><span class="flow-step">2</span><div><h2>{{ t('resources.flow2') }}</h2><p>{{ t('resources.flow2_hint') }}</p></div></div>
        <div class="cards cards-4 reveal-stagger">
          <article v-for="item in kit.slice(1)" :key="item.n" v-tilt class="card card-lift">
            <span class="label accent">{{ item.n }}</span>
            <h3 class="mt-3">{{ t(item.title) }}</h3>
            <p>{{ t(item.desc) }}</p>
            <p class="mt-5">
              <router-link v-if="item.route" class="btn sm" :to="item.href">{{ t(item.label) }} →</router-link>
              <a v-else class="btn sm" :href="item.href" :download="item.view ? undefined : ''" :target="item.view ? '_blank' : undefined">{{ t(item.label) }} {{ item.view ? '→' : '↓' }}</a>
            </p>
          </article>
        </div>
      </div>

      <div class="flow-band reveal mt-16">
        <div class="flow-head"><span class="flow-step">3</span><div><h2>{{ t('resources.flow3') }}</h2><p>{{ t('resources.flow3_hint') }}</p></div></div>
      </div>
      <h2 class="label accent mt-8 mb-2">{{ t('resources.scenarios') }}</h2>
      <p class="text2 mb-6 max-w-3xl text-sm">{{ t('resources.scenarios_note') }}</p>
      <p v-if="loading" class="text3 text-sm">{{ t('common.loading') }}</p>
      <p v-else-if="!active.length" class="text3 text-sm">{{ t('common.no_data') }}</p>
      <div v-else class="scenario-grid">
        <article v-for="s in active" :key="s.id" class="scenario-card" :data-testid="`resources-scenario-${s.slug}`">
          <header class="scenario-head">
            <div>
              <h3 class="m text-lg text-text-primary">{{ s.slug }}</h3>
              <p class="text2 mt-1 text-sm">{{ s.name }}</p>
              <p v-if="s.description" class="text3 mt-1 text-xs">{{ s.description }}</p>
            </div>
            <span class="pill" :class="s.weather_public ? 'ok' : 'closed'">{{ s.weather_public ? t('resources.weather_public') : t('resources.weather_hidden') }}</span>
          </header>
          <dl class="scenario-stats">
            <div><dt>{{ t('resources.wallclock') }}</dt><dd>{{ fmtClock(s.global_wallclock_seconds) }}</dd></div>
            <div><dt>{{ t('resources.nights') }}</dt><dd>{{ s.n_nights ?? '—' }}</dd></div>
            <div><dt>{{ t('resources.slots') }}</dt><dd>{{ s.n_slots ?? '—' }}</dd></div>
            <div><dt>{{ t('resources.tiles_n') }}</dt><dd>{{ s.n_tiles ?? '—' }}</dd></div>
            <div><dt>{{ t('resources.targets') }}</dt><dd>{{ s.n_targets ?? '—' }}</dd></div>
            <div><dt>{{ t('resources.requests') }}</dt><dd>{{ s.n_requests ?? '—' }}</dd></div>
          </dl>
          <p v-if="competition.mode==='competition'" class="text2 mt-5 text-sm">{{ t('resources.session_data') }}</p>
          <template v-else><div v-for="g in GROUPS" :key="g" class="file-group">
            <div class="file-group-head">
              <span class="label">{{ t(`resources.file_group.${g}`) }}</span>
              <span v-if="!groupVisible(s, g)" class="pill closed">{{ t('resources.hidden') }}</span>
            </div>
            <p class="text3 text-xs">{{ t(`resources.file_group_desc.${g}`) }}</p>
            <div class="file-list">
              <template v-for="f in filesFor(g)" :key="f.key">
                <button v-if="scenarioFileVisible(s, f)" type="button" class="file-btn" :disabled="busy === `${s.slug}/${f.key}`" :data-testid="`dl-${s.slug}-${f.name}`" @click="download(s, f)">{{ f.name }} ↓</button>
                <span v-else class="file-btn is-hidden" :title="t('resources.hidden')">{{ f.name }}</span>
              </template>
            </div>
          </div>
          </template>
          <!-- No checksum here: for a hidden-weather scenario the per-file hashes make a six-digit seed
               brute-forceable offline. Public scenarios still carry it inside scenario_manifest.json. -->
          <p class="text3 mt-3 text-xs m">{{ t('resources.contract') }}: {{ s.contract ?? 'challenge-score-v3' }}<template v-if="!s.weather_public"> · {{ t('resources.seed_hidden') }}</template></p>
        </article>
      </div>

      <h2 class="label accent mt-20 mb-4">{{ t('resources.cli') }}</h2>
      <pre class="code-block" tabindex="0">{{ cli }}</pre>
    </div></section>
  </main>
</template>

<style scoped>
.flow-head { display: flex; align-items: flex-start; gap: 1.1rem; margin-bottom: 1.4rem; }
.flow-step { display: grid; place-items: center; width: 2.6rem; height: 2.6rem; flex: none;
  border: 1px solid rgba(251,191,36,.55); color: #fbbf24; font-family: 'Space Grotesk', system-ui, sans-serif;
  font-size: 1.25rem; font-weight: 600; background: rgba(251,191,36,.08); }
.flow-head h2 { font-size: 1.15rem; font-weight: 600; letter-spacing: -.01em; color: #f5f7ff; }
.flow-head p { margin-top: .25rem; font-size: .85rem; color: #aeb6c8; }
.flow-primary { border-color: rgba(251,191,36,.4); }
.cards.cards-1 { grid-template-columns: minmax(0, 1fr); }
.scenario-grid { display: grid; gap: 1.5rem; }
@media (min-width: 1100px) { .scenario-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.scenario-card { border: 1px solid rgba(158,173,255,.22); background: linear-gradient(180deg, rgba(38,48,86,.45), rgba(13,18,36,.9)); padding: 1.5rem; min-width: 0; }
.scenario-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
.scenario-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 1.25rem 0 0; border: 1px solid #2a2a2a; background: #2a2a2a; }
@media (min-width: 640px) { .scenario-stats { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
.scenario-stats > div { background: #10162c; padding: .6rem .7rem; min-width: 0; }
.scenario-stats dt { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .58rem; letter-spacing: .1em; text-transform: uppercase; color: #858585; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.scenario-stats dd { margin: .15rem 0 0; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .85rem; color: #f5f5f5; }
.file-group { margin-top: 1.25rem; }
.file-group-head { display: flex; align-items: center; gap: .75rem; margin-bottom: .2rem; }
.file-list { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .5rem; }
.file-btn { border: 1px solid #3a3a3a; padding: .25rem .55rem; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .7rem; color: #78a6ff; background: none; }
.file-btn:hover:not(:disabled):not(.is-hidden) { border-color: #78a6ff; color: #f5f5f5; }
.file-btn:disabled { opacity: .5; }
.file-btn.is-hidden { color: #6e6e6e; border-style: dashed; text-decoration: line-through; cursor: not-allowed; }
</style>
