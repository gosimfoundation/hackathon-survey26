<script setup lang="ts">
/**
 * Local-only page for paper figures: the homepage's 3D sky replay (ReplaySky3D.vue) rendered alone,
 * frozen at one chosen moment of the bundled demo run, on a plain black backdrop — no console frame,
 * HUD, narration or transport. The moment is picked with ?p=<loop progress 0…1> (an exposure's beat
 * puts the telescope mid-pointing with its fibres landed around p where phase ≈ 0.7); ?figure=0 turns
 * the inset's live caption back on. Nothing here changes the homepage: the figure look is the
 * `figure` prop on ReplaySky3D and this page, both inert by default.
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { replayActions, replayMeta, replaySite, replaySlots, replayTimeAt, settledCountAt, slotIndexAt, SLOT_SECONDS } from '../composables/useReplayClock'
import { lstDeg } from '../lib/skymap'
import { shownSettled } from '../lib/replayStory'
import ReplaySky3D, { type Sky3DFrame } from '../components/sections/ReplaySky3D.vue'

const route = useRoute()
const sky3d = shallowRef<InstanceType<typeof ReplaySky3D> | null>(null)
const ready = ref(false)
let raf = 0

const progress = () => {
  const p = Number(route.query.p)
  return Number.isFinite(p) ? Math.max(0, Math.min(0.999999, p)) : 0.19157
}
const figure = () => route.query.figure !== '0'

/** The same frame SkyConsole.builds each tick, but held at one loop position. */
function frameAt(p: number): Sky3DFrame {
  const fr = replayTimeAt(p)
  const action = replayActions[fr.actionIndex]
  const phase = action ? Math.max(0, Math.min(1, (fr.nowSec - action.startSec) / Math.max(1, action.doneSec - action.startSec))) : 0
  const live = !fr.gap && action?.a === 'observe' && action.center ? { index: fr.actionIndex, phase } : null
  const settled = shownSettled(settledCountAt(fr.nowSec), live)
  const sec = fr.lapseSec
  let slot = replaySlots.length ? replaySlots[slotIndexAt(sec)] : null
  if (slot && (sec < slot.startSec || sec >= slot.startSec + SLOT_SECONDS)) slot = null
  const prev = live ? replayActions[fr.actionIndex - 1] : null
  return {
    t: sec,
    lst: lstDeg(replaySite.lon, sec),
    settled,
    live,
    from: prev && prev.a === 'observe' && prev.center ? prev.center : null,
    open: slot ? slot.open : true,
    transp: slot ? slot.transp : 1,
    version: replayMeta.version,
  }
}

function loop() {
  sky3d.value?.draw(frameAt(progress()))
  raf = requestAnimationFrame(loop)
}
function start() {
  if (raf || replayActions.length === 0) return
  raf = requestAnimationFrame(loop)
}

onMounted(start)
// The demo replay arrives as its own chunk after first paint; start drawing once it lands.
watch(() => replayMeta.version, start, { flush: 'post' })
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>

<template>
  <div class="fig-sky">
    <ReplaySky3D ref="sky3d" :figure="figure()" @ready="ready = true" />
  </div>
</template>

<style scoped>
.fig-sky {
  position: fixed; inset: 0; z-index: 9999;
  background: #000;
}
/* Paper figure: keep the dome, labels and zoomed inset, drop the drag hint. */
.fig-sky :deep(.sky3d-hint) { display: none; }
</style>
