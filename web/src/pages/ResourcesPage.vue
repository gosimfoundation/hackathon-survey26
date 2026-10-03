<script setup lang="ts">
import { useScrollReveal } from '../composables/useScrollReveal'
useScrollReveal()
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../composables/useI18n'
import { isSupabaseConfigured } from '../lib/supabase'
import { FORMAL_CARDS, type CardLanguage, type TaskCard } from '../lib/taskCards'
import { bundledCardTitle, downloadCardZip, practiceCards, releasedCardFiles } from '../lib/taskCardSource'
import { useFlash } from '../stores/flash'
import PageHead from '../components/layout/PageHead.vue'
import { assetUrl } from '../composables/api'

const { t, tf, locale } = useI18n()
const flash = useFlash()

// Pinned to the examples-2026-10-02 release tag, not releases/latest/download/... -- this
// repo's own site-publish workflow (.github/workflows/publish-site.yml) mints a new "Website"
// release and marks it --latest on every successful push to main, so "latest" here would almost
// immediately redirect to a site tarball instead of this zip. Re-run scripts/build-examples-bundle.sh
// to update the asset on this same tag.
const EXAMPLES_BUNDLE_URL = 'https://github.com/gosimfoundation/hackathon-survey26/releases/download/examples-2026-10-02/gosim-observer-examples.zip'

// A language's card only appears once examples/<lang>/ is published and its ZIP is built --
// see web/scripts/build-examples.mjs. Adding another language later is one entry here.
const exampleProjects = [
  { lang: 'python', name: 'Python', descKey: 'resources.example_python_desc', available: true },
  { lang: 'typescript', name: 'TypeScript', descKey: 'resources.example_typescript_desc', available: true },
  { lang: 'rust', name: 'Rust', descKey: 'resources.example_rust_desc', available: true },
] as const

// Talk recordings are too large for the repo/site tarball (two exceed GitHub's 100 MB file cap),
// so they live as assets on the talks-2026-10 release. That release is a prerelease on purpose:
// the shared publisher deploys whatever release is "latest" and refuses anything not tagged site-*.
const TALKS_BASE_URL = 'https://github.com/gosimfoundation/hackathon-survey26/releases/download/talks-2026-10/'
const talks = [
  {
    id: 'yifei-luo', date: '2026-10-02', poster: '/media/talks/talk-yifei-luo-20261002.jpg',
    titleKey: 'resources.talk1_title', speakersKey: 'resources.talk1_speakers',
    parts: [
      { labelKey: 'resources.talk_part_lecture', file: 'talk1-yifei-luo-20261002-part1-lecture.mp4' },
      { labelKey: 'resources.talk_part_qa', file: 'talk1-yifei-luo-20261002-part2-qa.mp4' },
    ],
  },
  {
    id: 'wang-li', date: '2026-10-03', poster: '/media/talks/talk-wang-li-20261003.jpg',
    titleKey: 'resources.talk2_title', speakersKey: 'resources.talk2_speakers',
    parts: [
      { labelKey: 'resources.talk_part_1', file: 'talk2-wang-li-20261003-part1.mp4' },
      { labelKey: 'resources.talk_part_2', file: 'talk2-wang-li-20261003-part2.mp4' },
    ],
  },
] as const

const hiddenCards = ['E', 'F', 'G', 'H']
const kit = computed(() => [
  { n: '01', title: 'resources.docs', desc: 'resources.docs_desc', href: '/docs', primary: false, label: 'common.view', route: true },
])
const language = computed<CardLanguage>(() => locale.value === 'zh' ? 'zh' : 'en')
const taskCards = [...practiceCards, ...FORMAL_CARDS]
const cardFiles = ref<Record<string, string[] | undefined>>({})
const cardBusy = ref<string | null>(null)
async function downloadCard(card: TaskCard) {
  cardBusy.value = card.id
  try { await downloadCardZip(card, cardFiles.value[card.id] ?? []) }
  catch { flash.error(t('subs.download_failed')) }
  finally { cardBusy.value = null }
}

onMounted(async () => {
  if (isSupabaseConfigured) for (const card of taskCards) {
    releasedCardFiles(card).then(files => { cardFiles.value = { ...cardFiles.value, [card.id]: files } })
      .catch(() => { cardFiles.value = { ...cardFiles.value, [card.id]: [] } })
  }
})
</script>

<template>
  <main class="poster-canvas">
    <PageHead :kicker="t('resources.kicker')" :title="t('resources.title')" :lede="t('resources.lede')" />
    <section class="section"><div class="wrap">
      <div class="flow-band reveal">
        <div class="flow-head"><div><h2>{{ t('resources.flow_cards') }}</h2><p>{{ t('resources.flow_cards_hint') }}</p></div></div>
        <div class="task-card-grid">
          <article v-for="c in taskCards" :key="c.id" class="task-card-item" :data-testid="`resources-card-${c.id}`">
            <span class="label" :class="{ accent: c.stage === 'practice' }">{{ c.stage === 'practice' ? t('cards_page.practice') : t('cards_page.formal') }}</span>
            <h3 class="mt-2">{{ c.stage === 'practice' ? bundledCardTitle(c, language) : tf('resources.card_formal_title', { card: c.symbol }) }}</h3>
            <p class="task-card-actions">
              <router-link class="btn sm" :to="`/cards/${c.id}`">{{ t('resources.card_view') }} →</router-link>
              <button v-if="cardFiles[c.id]?.length" type="button" class="btn sm" :disabled="cardBusy === c.id" :data-testid="`card-zip-${c.id}`" @click="downloadCard(c)">{{ t('resources.card_zip') }} ↓</button>
              <span v-else-if="cardFiles[c.id]" class="pill" :class="c.stage === 'practice' ? 'upcoming' : 'closed'">{{ c.stage === 'practice' ? t('resources.card_pending') : t('resources.card_locked') }}</span>
            </p>
          </article>
          <div class="hidden-cards-note" data-testid="resources-hidden-cards-note">
            <h3>{{ t('resources.hidden_note_title') }}</h3>
            <p>{{ t('resources.hidden_note_p1') }}</p>
            <p>{{ t('resources.hidden_note_p2') }}</p>
            <p>{{ t('resources.hidden_note_p3') }}</p>
            <p>{{ t('resources.hidden_note_p4') }}</p>
          </div>
          <article v-for="symbol in hiddenCards" :key="`hidden-${symbol}`" class="task-card-item" :data-testid="`resources-card-hidden-${symbol.toLowerCase()}`">
            <span class="label">{{ t('resources.card_hidden_label') }}</span>
            <h3 class="mt-2">{{ tf('resources.card_hidden_title', { card: symbol }) }}</h3>
            <p class="task-card-actions">
              <span class="pill closed">{{ t('resources.card_not_public') }}</span>
            </p>
          </article>
        </div>
      </div>

      <div id="examples" class="flow-band reveal mt-16">
        <div class="flow-head"><div><h2>{{ t('resources.flow_examples') }}</h2><p>{{ t('resources.flow_examples_hint') }}</p></div></div>
        <p class="examples-bundle-cta">
          <a class="btn primary" :href="EXAMPLES_BUNDLE_URL" data-testid="examples-bundle-download">{{ t('resources.examples_bundle_download') }} ↓</a>
        </p>
        <div class="cards cards-3 reveal-stagger">
          <article v-for="ex in exampleProjects" :key="ex.lang" v-tilt class="card card-lift" :data-testid="`example-card-${ex.lang}`">
            <span class="label accent">{{ ex.name }}</span>
            <h3 class="mt-3">{{ ex.name }}</h3>
            <p>{{ t(ex.descKey) }}</p>
            <p v-if="ex.available" class="example-actions mt-5">
              <a class="btn sm" :href="`https://github.com/gosimfoundation/hackathon-survey26/tree/main/examples/${ex.lang}`" target="_blank" rel="noopener">{{ t('resources.example_github') }} →</a>
            </p>
            <p v-else class="mt-5"><span class="pill upcoming">{{ t('resources.card_pending') }}</span></p>
          </article>
        </div>
      </div>

      <div id="talks" class="flow-band reveal mt-16">
        <div class="flow-head"><div><h2>{{ t('resources.flow_talks') }}</h2><p>{{ t('resources.flow_talks_hint') }}</p></div></div>
        <div class="talk-list">
          <article v-for="talk in talks" :key="talk.id" class="talk-item" :data-testid="`talk-${talk.id}`">
            <span class="label accent">{{ talk.date }}</span>
            <h3 class="mt-2">{{ t(talk.titleKey) }}</h3>
            <p class="talk-speakers">{{ t(talk.speakersKey) }}</p>
            <div class="talk-parts">
              <figure v-for="part in talk.parts" :key="part.file" class="talk-part">
                <video controls preload="none" playsinline :poster="assetUrl(talk.poster)">
                  <source :src="TALKS_BASE_URL + part.file" type="video/mp4">
                </video>
                <figcaption>
                  <span>{{ t(part.labelKey) }}</span>
                  <a :href="TALKS_BASE_URL + part.file" target="_blank" rel="noopener">{{ t('resources.talk_download') }} ↓</a>
                </figcaption>
              </figure>
            </div>
          </article>
        </div>
      </div>

      <div class="flow-band reveal mt-16">
        <div class="flow-head"><div><h2>{{ t('resources.flow2') }}</h2><p>{{ t('resources.flow2_hint') }}</p></div></div>
        <div class="cards cards-1 reveal-stagger">
          <article v-for="item in kit" :key="item.title" v-tilt class="card card-lift">
            <span class="label accent">{{ item.n }}</span>
            <h3 class="mt-3">{{ t(item.title) }}</h3>
            <p>{{ t(item.desc) }}</p>
            <p class="mt-5">
              <router-link class="btn sm" :to="item.href">{{ t(item.label) }} →</router-link>
            </p>
          </article>
        </div>
      </div>

    </div></section>
  </main>
</template>

<style scoped>
.flow-head { display: flex; align-items: flex-start; gap: 1.1rem; margin-bottom: 1.4rem; }
.flow-head h2 { font-size: 1.15rem; font-weight: 600; letter-spacing: -.01em; color: #f5f7ff; }
.flow-head p { margin-top: .25rem; font-size: .85rem; color: #aeb6c8; }
.flow-primary { border-color: rgba(251,191,36,.4); }
.cards.cards-1 { grid-template-columns: minmax(0, 1fr); }
.task-card-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); }
@media (min-width: 900px) { .task-card-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.task-card-item { border: 1px solid rgba(158,173,255,.22); background: rgba(13,18,36,.7); padding: 1.1rem 1.2rem; min-width: 0; }
.task-card-item h3 { font-size: 1rem; line-height: 1.4; color: #f5f7ff; }
.task-card-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: 1rem; }
.hidden-cards-note { grid-column: 1 / -1; border: 1px solid rgba(251,191,36,.3); background: rgba(251,191,36,.06); padding: 1.1rem 1.2rem; }
.hidden-cards-note h3 { font-size: .95rem; color: #fbbf24; margin-bottom: .5rem; }
.hidden-cards-note p { font-size: .875rem; line-height: 1.5; color: rgba(245,247,255,.78); margin-top: .4rem; }
.example-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
.examples-bundle-cta { margin-bottom: 1.25rem; }
.talk-list { display: grid; gap: 1rem; }
.talk-item { border: 1px solid rgba(158,173,255,.22); background: rgba(13,18,36,.7); padding: 1.1rem 1.2rem; min-width: 0; }
.talk-item h3 { font-size: 1rem; line-height: 1.4; color: #f5f7ff; }
.talk-speakers { margin-top: .3rem; font-size: .85rem; color: #aeb6c8; }
.talk-parts { display: grid; gap: 1rem; margin-top: 1rem; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); }
.talk-part { margin: 0; min-width: 0; }
.talk-part video { display: block; width: 100%; aspect-ratio: 2 / 1; background: #05070f; object-fit: contain; }
.talk-part figcaption { display: flex; justify-content: space-between; gap: .5rem; margin-top: .45rem; font-size: .8rem; color: #aeb6c8; }
.talk-part figcaption a { color: #b9c5ff; }
</style>
