<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { replayActions, replayMeta, replayNetPrefix, replayNights, replayObserves, replaySite, replaySlots, replayTiles, replayTimeAt, replayTotals, replayHasCursor, replayPulseSec, settledCountAt, useReplayClock, SLOT_SECONDS } from '../../composables/useReplayClock'
import { drawSkyMap, lstDeg, PAD, type ObservedMark } from '../../lib/skymap'
import { OUTCOME_COLORS } from '../../lib/report'
import { fmtUtc, num } from '../../lib/format'
import { overlayActive, releaseOverlay, requestOverlay } from '../../stores/overlay'

const { t, tf } = useI18n()
const clock = useReplayClock()
const canvas = ref<HTMLCanvasElement | null>(null)
const progressUI = ref(0)
const scrubbing = ref(false)
const lstOpen = ref(false)
const seekValue = computed(() => Math.round(progressUI.value * 1000))
function onSeek(e: Event) {
  const v = (e.target as HTMLInputElement).valueAsNumber / 1000
  progressUI.value = v
  clock.seek(v)
}
const hud = ref({ slot: '', night: '', date: '', utc: '', lst: '', seeing: 0, transp: 0, sky: 0, eff: 0, open: true, score: 0, completed: 0, nightNo: 1 })
/** What the replay is doing right now, so viewers who do not know the task can follow along. */
const beat = ref<{ key: string; region: string; nightNo: number; n: number }>({ key: 'idle', region: '', nightNo: 1, n: 0 })
const paused = computed(() => clock.state.paused)
const reduced = computed(() => clock.state.reduced)
let raf = 0, observer: ResizeObserver | undefined, shownScore = 0, lastProgress = 0
const PULSE = SLOT_SECONDS * 2  // glow for two slots of replay time after a tile completes
/** Stands in for the weather row when a run arrives without one, so the readout stays up instead of throwing. */
const EMPTY_SLOT = { slot: '—', night: '', t: '', startSec: 0, open: true, seeing: 0, transp: 0, sky: 0, eff: 0 }
const nightIds = computed(() => { void replayMeta.version; return replayNights })
const tileById = computed(() => { void replayMeta.version; return new Map(replayTiles.map(tile => [tile.id, tile])) })

const narration = computed(() => tf(`hero.console.beat.${beat.value.key}`, { region: beat.value.region, night: beat.value.nightNo, nights: replayTotals.nights, n: beat.value.n }))
/** Where the meridian sits inside the canvas box, so the walkthrough can point at the line wherever it is. */
const meridianLeft = ref('50%')
function trackMeridian(nowSec: number) {
  const el = canvas.value
  if (!el || !el.clientWidth) return
  const plot = el.clientWidth - PAD.left - PAD.right
  const px = PAD.left + (lstDeg(replaySite.lon, nowSec) / 360) * plot
  meridianLeft.value = `${(px / el.clientWidth) * 100}%`
}

function frameAt(progress: number) {
  const { slotIndex, nowSec, skySec, skyFade, actionIndex, gap } = replayTimeAt(progress)
  // Everything finished by now, counted off the clock so it stays right however the beats are paced.
  const settled = settledCountAt(nowSec)
  const score = replayNetPrefix[Math.max(0, Math.min(replayNetPrefix.length - 1, settled))] ?? 0
  const observed = new Map<string, ObservedMark>()
  for (const entry of replayObserves) {
    if (entry.i >= settled) break
    const a = entry.a
    if (!a.tile) continue
    const prev = observed.get(a.tile)
    if (!prev || a.cls === 'completed') observed.set(a.tile, { state: a.cls, doneSec: a.doneSec })
  }
  // Distinct finished tiles, so a re-observation never inflates the count past the catalogue.
  let completed = 0
  for (const mark of observed.values()) if (mark.state === 'completed') completed++
  return { slotIndex, nowSec, skySec, skyFade, observed, score, completed, actionIndex, gap }
}

/** Pick the line of commentary for what the replay is showing: an exposure, or a collapsed quiet stretch. */
function beatFor(actionIndex: number, gap: { nights: number; slots: number } | null, open: boolean, nightNo: number) {
  if (gap) {
    if (gap.nights > 1) return { key: 'gap_nights', region: '', nightNo, n: gap.nights }
    if (!open) return { key: 'dome_closed', region: '', nightNo, n: 0 }
    return { key: 'gap_short', region: '', nightNo, n: 0 }
  }
  const action = replayActions[actionIndex]
  if (!action) return { key: 'idle', region: '', nightNo, n: 0 }
  const tile = tileById.value.get(action.tile)
  const key = action.cls === 'completed' ? (tile?.cls === 'R' ? 'observe_required' : 'observe') : 'interrupted'
  return { key, region: tile?.region ?? '', nightNo, n: 0 }
}

function render() {
  const progress = clock.replayProgress()
  const { slotIndex, nowSec, skySec, skyFade, observed, score, completed, actionIndex, gap } = frameAt(progress)
  if (progress < lastProgress) shownScore = 0  // loop restarted
  lastProgress = progress
  if (!scrubbing.value) progressUI.value = progress
  shownScore = reduced.value ? score : shownScore + (score - shownScore) * 0.18
  const slot = replaySlots[slotIndex] ?? EMPTY_SLOT
  const stamp = fmtUtc(new Date(nowSec * 1000).toISOString(), { seconds: true, short: true })
  const lstHours = lstDeg(replaySite.lon, nowSec) / 15
  const lst = `${String(Math.floor(lstHours)).padStart(2, '0')}:${String(Math.floor((lstHours % 1) * 60)).padStart(2, '0')}`
  const nightNo = nightIds.value.indexOf(slot.night) + 1
  hud.value = { slot: slot.slot, night: slot.night, date: stamp.slice(0, 5), utc: stamp.slice(6), lst, seeing: slot.seeing, transp: slot.transp, sky: slot.sky, eff: slot.eff, open: slot.open, score: shownScore, completed, nightNo }
  beat.value = beatFor(actionIndex, gap, slot.open, nightNo)
  trackMeridian(skySec)
  if (canvas.value) drawSkyMap(canvas.value, replayTiles, replaySite, { nowSec: skySec, observed, timeFade: skyFade, pulseSeconds: reduced.value ? 0 : Math.max(PULSE, replayPulseSec) })
}
function loop() { render(); if (!reduced.value) raf = requestAnimationFrame(loop) }

// --- first-visit walkthrough -------------------------------------------------
// Four beats explaining the axes, the marks, the meridian (and its jump) and the readout. Shown once per
// browser; the replay keeps running behind it, paused so nothing moves while reading.
const TOUR_KEY = 'sac.sky-tour.seen'
const TOUR_OVERLAY = 'sky-tour'
const ALL_TOUR_STEPS = ['axes', 'tiles', 'meridian', 'hud'] as const
/** False on runs long enough that the time cursor is left out; the walkthrough then skips its step. */
const cursorShown = computed(() => { void replayMeta.version; return replayHasCursor })
const TOUR_STEPS = computed(() => ALL_TOUR_STEPS.filter(step => step !== 'meridian' || cursorShown.value))
const tourStep = ref(-1)
const tourOpen = computed(() => tourStep.value >= 0)
const currentStep = computed(() => TOUR_STEPS.value[tourStep.value] ?? null)

function startTour() { tourStep.value = 0; clock.setPaused(true) }
function nextStep() {
  if (tourStep.value < TOUR_STEPS.value.length - 1) { tourStep.value += 1; return }
  endTour()
}
function endTour() {
  tourStep.value = -1
  releaseOverlay(TOUR_OVERLAY)
  clock.setPaused(false)
  try { window.localStorage.setItem(TOUR_KEY, '1') } catch { /* private mode */ }
}

onMounted(() => {
  if (canvas.value) { observer = new ResizeObserver(() => render()); observer.observe(canvas.value) }
  loop()
  let seen = true
  try { seen = window.localStorage.getItem(TOUR_KEY) === '1' } catch { /* private mode: do not nag */ }
  // The first-visit walkthrough waits its turn behind another overlay (a pinned announcement popup).
  if (!seen && !clock.state.reduced) requestOverlay(TOUR_OVERLAY)
})
watch(() => overlayActive(TOUR_OVERLAY), active => { if (active && tourStep.value < 0) startTour() })
// The frame loop does not run under reduced motion, so a newly loaded run has to be drawn on arrival.
watch(() => replayMeta.version, () => render(), { flush: 'post' })
// A run swapped in mid-walkthrough can drop the cursor step; keep the walkthrough on a step that exists.
watch(() => TOUR_STEPS.value.length, n => { if (tourStep.value >= n) tourStep.value = n - 1 })
function onHover(e: PointerEvent, inside: boolean) {
  if (e.pointerType !== 'mouse' || tourOpen.value) return
  clock.setPaused(inside)
}

onUnmounted(() => { cancelAnimationFrame(raf); observer?.disconnect(); releaseOverlay(TOUR_OVERLAY) })
</script>

<template>
  <div class="sky-console" data-testid="sky-console" :data-replay-source="replayMeta.source" @pointerenter="onHover($event, true)" @pointerleave="onHover($event, false)">
    <div class="sky-console-head">
      <span class="sky-live-title flex items-center gap-3"><span class="live-dot" :class="{ 'is-paused': paused || reduced }"></span><span>{{ t('hero.console.title') }}</span></span>
      <span class="flex items-center gap-4">
        <span class="text-white/60">{{ paused ? t('hero.console.paused') : tf('hero.console.replay_note', { nights: replayTotals.nights, actions: replayActions.length }) }}</span>
        <button type="button" class="replay-toggle" :aria-pressed="paused" :disabled="reduced" @click="clock.setPaused(!paused)">{{ paused ? t('hero.console.resume') : t('hero.console.pause') }}</button>
      </span>
    </div>
    <p class="sky-explainer">
      {{ t('hero.console.explainer') }}
      <button type="button" class="sky-tour-link" @click="startTour">{{ t('hero.console.tour_replay') }}</button>
    </p>
    <div class="sky-stage">
      <canvas ref="canvas" class="sky-canvas" role="img" :aria-label="t('hero.console.aria')"></canvas>
      <!-- Hover label for the cursor: only when a cursor is drawn, and only for a mouse — a tap sends no "leave" and pinned it open. -->
      <div v-if="cursorShown" class="sky-meridian-hit" :style="{ left: meridianLeft }" aria-hidden="true" @pointerenter="e => { if (e.pointerType === 'mouse') lstOpen = true }" @pointerleave="lstOpen = false"></div>
      <div v-if="lstOpen && cursorShown" class="sky-lst" :style="{ left: meridianLeft }">{{ tf('hero.console.lst', { lst: hud.lst }) }}</div>
      <div v-if="tourOpen" class="sky-tour" role="dialog" aria-modal="false" :aria-label="t('hero.console.tour_title')">
        <!-- The spotlight's shade stops at the sky map; unclipped it darkened the whole hero, title and buttons included. -->
        <div class="sky-tour-shade" aria-hidden="true">
          <div
            class="sky-tour-spot"
            :class="`is-${currentStep}`"
            :style="currentStep === 'meridian' ? { left: `calc(${meridianLeft} - 3%)` } : undefined"
          ></div>
        </div>
        <div class="sky-tour-card" :class="`at-${currentStep}`">
          <button type="button" class="sky-tour-close" :aria-label="t('hero.console.tour_close')" data-testid="sky-tour-close" @click="endTour">×</button>
          <p class="sky-tour-step">{{ tourStep + 1 }} / {{ TOUR_STEPS.length }}</p>
          <p class="sky-tour-text">{{ t(`hero.console.tour.${currentStep}`) }}</p>
          <p class="sky-tour-actions">
            <button type="button" class="replay-toggle" @click="nextStep">
              {{ tourStep === TOUR_STEPS.length - 1 ? t('hero.console.tour_done') : t('hero.console.tour_next') }}
            </button>
            <button type="button" class="sky-tour-link" @click="endTour">{{ t('hero.console.tour_skip') }}</button>
          </p>
        </div>
      </div>
    </div>
    <div class="sky-seek">
      <input
        type="range" min="0" max="1000" step="1"
        :value="seekValue" :disabled="reduced" :aria-label="t('hero.console.seek')"
        @pointerdown="scrubbing = true" @pointerup="scrubbing = false" @pointercancel="scrubbing = false"
        @input="onSeek"
      >
    </div>
    <p class="sky-narration" aria-live="polite" data-testid="sky-narration">
      <span class="sky-narration-dot" :class="{ 'is-wait': beat.key !== 'observe' && beat.key !== 'observe_required' }"></span>
      {{ narration }}
    </p>
    <div class="sky-legend" aria-hidden="true">
      <span><i class="diamond"></i>{{ t('hero.console.legend_required') }}</span>
      <span><i style="border-color:#78a6ff"></i>{{ t('hero.console.legend_flexible') }}</span>
      <span><i :style="{ background: OUTCOME_COLORS.completed, borderColor: OUTCOME_COLORS.completed }"></i>{{ t('hero.console.legend_completed') }}</span>
      <span><i :style="{ borderColor: OUTCOME_COLORS.interrupted }"></i>{{ t('hero.console.legend_interrupted') }}</span>
      <span v-if="cursorShown"><i class="ring"></i>{{ t('hero.console.legend_visible') }}</span>
      <span v-if="cursorShown"><i class="meridian"></i>{{ t('hero.console.legend_meridian') }}</span>
    </div>
    <dl class="sky-hud" aria-live="off">
      <div class="sky-hud-slot"><dt>{{ t('hero.console.slot') }}</dt><dd data-testid="sky-slot">{{ hud.slot }}</dd></div>
      <div><dt>UTC {{ hud.date }} · {{ hud.nightNo }}/{{ replayTotals.nights }}</dt><dd>{{ hud.utc }}</dd></div>
      <div class="sky-hud-weather" :title="t('hero.console.weather_help')">
        <dt>{{ t('hero.console.weather') }}</dt>
        <dd v-if="hud.open">{{ num(hud.seeing, 2) }}″ · {{ num(hud.transp, 2) }} · {{ num(hud.sky, 2) }} · {{ num(hud.eff, 2) }}</dd>
        <dd v-else class="text-[#ff6b6b]">{{ t('hero.console.dome_closed') }}</dd>
      </div>
      <div><dt>{{ t('hero.console.score') }}</dt><dd class="text-[#78a6ff]">{{ num(hud.score, 1) }}</dd></div>
      <div><dt>{{ t('hero.console.tiles') }}</dt><dd>{{ hud.completed }} / {{ replayTiles.length }}</dd></div>
    </dl>
  </div>
</template>

<style scoped>
.sky-console {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(255,255,255,.28);
  /* Sides fall away towards the bottom instead of ruling a flat rectangle. */
  border-image: linear-gradient(180deg, rgba(255,255,255,.4), rgba(255,255,255,.28) 45%, rgba(255,255,255,.1)) 1;
  background: rgba(2,5,12,.72);
}
.sky-console::before {
  position: absolute; top: -1px; left: 0; width: 3.5rem; height: 2px; content: ''; background: #315efb;
}
.sky-console-head {
  display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
  padding: .7rem .9rem;
  border-bottom: 1px solid rgba(255,255,255,.16);
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; color: #a8a8a8;
}
.live-dot.is-paused { animation: none; opacity: .5; }
.sky-seek { padding: .5rem .9rem .15rem; }
.sky-seek input { display: block; width: 100%; height: 4px; margin: 0; accent-color: #315efb; cursor: pointer; }
.sky-seek input:disabled { opacity: .35; cursor: default; }
.replay-toggle {
  border: 1px solid rgba(255,255,255,.28);
  padding: 2px 10px;
  font: inherit;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: rgba(255,255,255,.75);
  background: transparent;
  cursor: pointer;
}
.replay-toggle:hover:not(:disabled) { border-color: #315efb; color: #78a6ff; }
.replay-toggle:disabled { opacity: .4; cursor: default; }
.sky-explainer {
  margin: 0;
  padding: .6rem .9rem;
  border-bottom: 1px solid rgba(255,255,255,.1);
  font-size: .78rem; line-height: 1.6; color: rgba(255,255,255,.62);
}
.sky-tour-link {
  border: 0; padding: 0; margin-left: .35rem;
  font: inherit; color: #78a6ff; background: none; cursor: pointer; text-decoration: underline;
}
.sky-stage { position: relative; }
.sky-canvas { display: block; width: 100%; aspect-ratio: 3 / 2; min-height: 200px; }

.sky-tour { position: absolute; inset: 0; background: rgba(2,5,12,.55); }
.sky-tour-shade { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
/* the spotlight boxes track the canvas padding in lib/skymap.ts (left 30, right 10, top 16, bottom 18) */
.sky-tour-spot { position: absolute; border: 1px solid #78a6ff; box-shadow: 0 0 0 9999px rgba(2,5,12,.55); }
.sky-tour-spot.is-axes { left: 0; right: 0; bottom: 0; height: 22%; }
.sky-tour-spot.is-tiles { left: 8%; right: 8%; top: 18%; height: 46%; }
.sky-tour-spot.is-meridian { width: 6%; top: 0; bottom: 14%; }  /* left is bound to the live meridian */
.sky-tour-spot.is-hud { left: 0; right: 0; bottom: -1px; height: 12%; border-color: transparent; box-shadow: none; }
.sky-tour-card {
  position: absolute; left: 50%; transform: translateX(-50%);
  width: min(30rem, calc(100% - 2rem));
  padding: .85rem 1rem;
  border: 1px solid rgba(120,166,255,.55);
  background: rgba(4,8,18,.96);
}
.sky-tour-card.at-axes, .sky-tour-card.at-hud { top: 12%; }
.sky-tour-card.at-tiles, .sky-tour-card.at-meridian { bottom: 8%; }
.sky-tour-step {
  margin: 0 0 .35rem;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .6rem; letter-spacing: .12em; color: #78a6ff;
}
.sky-tour-text { margin: 0; font-size: .82rem; line-height: 1.65; color: #f5f5f5; }
/* An always-visible close control: the plain "skip" link was easy to miss. */
.sky-tour-close {
  position: absolute; top: .35rem; right: .5rem;
  width: 1.6rem; height: 1.6rem; padding: 0;
  border: 1px solid rgba(255,255,255,.35); border-radius: 50%;
  background: rgba(255,255,255,.08); color: #f5f5f5;
  font-size: 1rem; line-height: 1; cursor: pointer;
}
.sky-tour-close:hover { border-color: #78a6ff; color: #78a6ff; }
.sky-tour-actions { display: flex; align-items: center; gap: .9rem; margin: .7rem 0 0; }

.sky-narration {
  display: flex; align-items: center; gap: .5rem;
  margin: 0; padding: .55rem .9rem;
  border-top: 1px solid rgba(255,255,255,.1);
  font-size: .78rem; color: rgba(255,255,255,.85);
  min-height: 2.4rem;
}
.sky-narration-dot { width: .4rem; height: .4rem; flex: none; border-radius: 50%; background: #315efb; }
.sky-narration-dot.is-wait { background: rgba(255,255,255,.35); }
.sky-legend {
  display: flex; flex-wrap: wrap; gap: .4rem 1rem;
  padding: .45rem .9rem;
  border-top: 1px solid rgba(255,255,255,.1);
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .62rem; letter-spacing: .1em; text-transform: uppercase; color: rgba(255,255,255,.5);
}
.sky-legend i { display: inline-block; width: .55rem; height: .55rem; margin-right: .4rem; border: 1px solid; vertical-align: middle; }
.sky-legend i.diamond { border-color: #f5f5f5; transform: rotate(45deg) scale(.85); }
.sky-legend i.ring { border-color: rgba(255,255,255,.5); border-radius: 50%; }
.sky-legend i.meridian { width: 0; height: .7rem; border-width: 0 0 0 1px; border-style: dashed; border-color: #315efb; }
.sky-hud {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0;
  margin: 0; border-top: 1px solid rgba(255,255,255,.16);
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums;
}
.sky-hud > div { min-width: 0; padding: .6rem .55rem; border-right: 1px solid rgba(255,255,255,.1); border-bottom: 1px solid rgba(255,255,255,.1); }
.sky-hud dt { font-size: .58rem; letter-spacing: .07em; text-transform: uppercase; color: rgba(255,255,255,.45); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sky-hud dd { margin: .15rem 0 0; font-size: .72rem; color: #f5f5f5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sky-hud-weather { grid-column: span 2; }
@media (min-width: 640px) {
  .sky-hud { grid-template-columns: auto auto minmax(0, 1fr) auto auto; }
  .sky-hud-slot, .sky-hud-weather { grid-column: auto; }
  .sky-hud > div { border-bottom: 0; }
  .sky-hud > div:last-child { border-right: 0; }
}
.sky-console-head .sky-live-title { font-size: 1.04rem; font-weight: 650; letter-spacing: .01em; color: #fff; text-transform: none; }
.sky-console-head .sky-champ { display: inline-flex; align-items: center; gap: .4rem; color: #ffd27a; font-weight: 700; margin-left: .55rem; }
.sky-champ :deep(.user-avatar) { width: 22px; height: 22px; font-size: .62rem; }
.sky-topscore { color: #ffd27a; }
.sky-meridian-hit { position: absolute; top: 0; bottom: 0; width: 14px; transform: translateX(-50%); cursor: help; z-index: 3; }
.sky-lst { position: absolute; top: 10px; transform: translateX(-50%); z-index: 6; white-space: nowrap; padding: .32rem .6rem; border: 1px solid rgba(148,163,255,.45); background: rgba(5,9,20,.94); font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .62rem; letter-spacing: .05em; color: #cfe0ff; pointer-events: none; }
</style>
