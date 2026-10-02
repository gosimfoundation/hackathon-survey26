<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import WechatGroup from '../WechatGroup.vue'
import { replayMeta, replaySlots, useReplayClock } from '../../composables/useReplayClock'
const { t, pick } = useI18n()

// Click the 900 S label for one true little fact about what fits into 900 seconds.
const FACTS_ZH = [
  '900 秒里，月亮在天上悄悄挪了约 0.14 度——差不多它自己直径的四分之一。',
  '900 秒里，地球转过 3.75 度：头顶的星空滑过了七个多月亮的宽度。',
  '光走 900 秒约 2.7 亿公里——从太阳出发，飞过火星还有富余。',
  '900 秒里，国际空间站飞了近 7000 公里，比北京到莫斯科还远。',
  '900 秒里，旅行者 1 号又离太阳远了约 15000 公里。',
  '真实的巡天望远镜，一晚上要做上百个这样的 900 秒决定。',
]
const FACTS_EN = [
  'In 900 seconds the Moon quietly slides about 0.14° across the sky — a quarter of its own width.',
  'In 900 seconds the Earth turns 3.75°: the sky overhead drifts by seven Moon-widths.',
  'Light travels about 270 million km in 900 seconds — from the Sun past Mars with room to spare.',
  'In 900 seconds the International Space Station covers almost 7,000 km — farther than Beijing to Moscow.',
  'In 900 seconds Voyager 1 gets another 15,000 km farther from the Sun.',
  'A real survey telescope makes a hundred or so of these 900-second calls every single night.',
]
const fact = ref('')
let factTimer: number | undefined
function nextFact() {
  const list = pick(FACTS_EN, FACTS_ZH) as unknown as string[]
  let f = fact.value
  while (f === fact.value) f = list[Math.floor(Math.random() * list.length)]!
  fact.value = f
  if (factTimer) window.clearTimeout(factTimer)
  factTimer = window.setTimeout(() => { fact.value = '' }, 9000)
}
const { state } = useReplayClock()
// A run can in principle arrive without weather rows; the ticker falls back to dashes rather than throwing.
const NO_SLOT = { slot: '—', night: '—', open: true }
const slot = computed(() => { void replayMeta.version; return replaySlots[state.slotIndex] ?? replaySlots[0] ?? NO_SLOT })
const progressPct = computed(() => `${(state.progress * 100).toFixed(1)}%`)
</script>

<template>
  <footer class="cosmos-footer border-t text-white">
    <div class="slot-ticker" data-testid="slot-ticker">
      <div class="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-1 px-5 md:px-10 xl:px-14">
        <button type="button" class="ticker-fact-btn" @click="nextFact">900 S · {{ t('footer.ticker.per_slot') }}</button>
        <span class="text-[#78a6ff]">{{ t('footer.ticker.slot') }} {{ slot.slot }}</span>
        <span class="hidden sm:inline">{{ slot.night }} · {{ slot.open ? t('footer.ticker.open') : t('footer.ticker.closed') }}</span>
        <span class="slot-ticker-bar ml-auto" :class="{ 'is-static': state.reduced }"><i :style="{ width: progressPct }"></i></span>
        <span v-if="fact" class="ticker-fact">{{ fact }}</span>
      </div>
    </div>
    <div class="relative z-10 mx-auto max-w-[1600px] px-5 py-10 md:px-10 xl:px-14">
      <div class="flex flex-col justify-between gap-8 md:flex-row md:items-end">
        <div>
          <div class="text-2xl font-semibold tracking-[-.05em] text-[#f5f5f5]">OPEN <span class="text-[#315efb]">/</span> OBSERVER</div>
          <div class="mt-3 max-w-xl text-xs leading-relaxed text-white/60">{{ t('footer.copyright') }}</div>
          <WechatGroup compact class="mt-6 text-white/80" />
        </div>
        <nav class="flex flex-wrap gap-5 font-mono text-xs uppercase tracking-[.12em] text-white/70">
          <router-link to="/rules" class="transition-colors hover:text-[#78a6ff]">{{ t('footer.links.rules') }}</router-link>
          <router-link to="/docs" class="transition-colors hover:text-[#78a6ff]">{{ t('footer.links.docs') }}</router-link>
          <router-link to="/announcements" class="transition-colors hover:text-[#78a6ff]">{{ t('nav.announcements') }}</router-link>
          <a :href="`mailto:${t('footer.contact_email')}`" class="transition-colors hover:text-[#78a6ff]">{{ t('footer.links.contact') }}</a>
          <a href="https://gosim.org" target="_blank" rel="noopener" class="transition-colors hover:text-[#78a6ff]">{{ t('footer.mainSite') }} ↗</a>
        </nav>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.slot-ticker { position: relative;
  border-bottom: 1px solid rgba(255,255,255,.14);
  padding: .55rem 0;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .66rem; letter-spacing: .12em; text-transform: uppercase; color: rgba(255,255,255,.5);
  font-variant-numeric: tabular-nums;
}
.ticker-fact-btn { font: inherit; letter-spacing: inherit; text-transform: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; transition: color .2s; }
.ticker-fact-btn:hover { color: #9db9ff; }
.ticker-fact { position: absolute; left: 1.25rem; bottom: calc(100% + 8px); max-width: min(540px, 86vw); padding: .6rem .85rem; border: 1px solid rgba(148,163,255,.4); background: rgba(6,10,22,.97); color: #dbe6ff; font-size: .68rem; letter-spacing: .04em; line-height: 1.65; text-transform: none; z-index: 40; }
.slot-ticker-bar { position: relative; width: 6rem; height: 3px; background: rgba(255,255,255,.12); }
.slot-ticker-bar i { position: absolute; left: 0; top: 0; bottom: 0; background: #315efb; }
.slot-ticker-bar.is-static i { width: 100% !important; }
</style>
