<script setup lang="ts">
import { useScrollReveal } from '../composables/useScrollReveal'
useScrollReveal()
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '../composables/useI18n'
import { appUrl } from '../composables/api'
import { isSupabaseConfigured } from '../lib/supabase'
import { FORMAL_CARDS, type CardLanguage, type TaskCard } from '../lib/taskCards'
import { bundledCardTitle, downloadCardZip, practiceCards, releasedCardFiles } from '../lib/taskCardSource'
import { useFlash } from '../stores/flash'
import PageHead from '../components/layout/PageHead.vue'

const { t, tf, locale } = useI18n()
const flash = useFlash()

const hiddenCards = ['E', 'F', 'G', 'H']
const kit = computed(() => [
  { n: '02', title: 'resources.skill_v4', desc: 'resources.skill_v4_desc', href: appUrl('/skill-v4.md'), primary: false, label: 'common.view', view: true },
  { n: '03', title: 'resources.cards', desc: 'resources.cards_desc', href: '/cards', primary: false, label: 'common.view', route: true },
  { n: '04', title: 'resources.docs', desc: 'resources.docs_desc', href: '/docs', primary: false, label: 'common.view', route: true },
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
        <div class="flow-head"><span class="flow-step">1</span><div><h2>{{ t('resources.flow_cards') }}</h2><p>{{ t('resources.flow_cards_hint') }}</p></div></div>
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
          <article v-for="symbol in hiddenCards" :key="`hidden-${symbol}`" class="task-card-item" :data-testid="`resources-card-hidden-${symbol.toLowerCase()}`">
            <span class="label">{{ t('resources.card_hidden_label') }}</span>
            <h3 class="mt-2">{{ tf('resources.card_hidden_title', { card: symbol }) }}</h3>
            <p class="task-card-actions">
              <span class="pill closed">{{ t('resources.card_not_public') }}</span>
            </p>
          </article>
        </div>
      </div>

      <div class="flow-band reveal mt-16">
        <div class="flow-head"><span class="flow-step">2</span><div><h2>{{ t('resources.flow2') }}</h2><p>{{ t('resources.flow2_hint') }}</p></div></div>
        <div class="cards cards-3 reveal-stagger">
          <article v-for="item in kit" :key="item.title" v-tilt class="card card-lift">
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
.task-card-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); }
@media (min-width: 900px) { .task-card-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
.task-card-item { border: 1px solid rgba(158,173,255,.22); background: rgba(13,18,36,.7); padding: 1.1rem 1.2rem; min-width: 0; }
.task-card-item h3 { font-size: 1rem; line-height: 1.4; color: #f5f7ff; }
.task-card-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin-top: 1rem; }
</style>
