<script setup lang="ts">
// 送测版本提醒: between the official deadline and the final-version lock, members of a team that has confirmed
// versions but no explicitly chosen final version get this popup, again 30 minutes after each dismissal
// (remembered in this browser). Teams that chose never see it. The database decides (observer_final_choice_pending).
import { onMounted, onUnmounted, ref, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '../../composables/useI18n'
import { useAuth } from '../../stores/auth'
import { supabase } from '../../lib/supabase'

const WINDOW_START = Date.parse('2026-10-07T15:59:59Z')
const WINDOW_END = Date.parse('2026-10-08T01:00:00Z')
const EVERY_MS = 30 * 60_000
const KEY = 'survey26-final-choice-reminder-at'
const { pick } = useI18n()
const { team } = useAuth()
const router = useRouter()
const dialog = ref<HTMLDialogElement | null>(null)
const open = ref(false)
let memoryAt = 0
let timer: number | undefined

function lastShown(): number {
  try { return Number(localStorage.getItem(KEY) || 0) || memoryAt } catch { return memoryAt }
}
function remember(at: number) {
  memoryAt = at
  try { localStorage.setItem(KEY, String(at)) } catch { /* in-memory only */ }
}

async function check() {
  const now = Date.now()
  if (open.value || !team.value?.id || now < WINDOW_START || now >= WINDOW_END) return
  if (now - lastShown() < EVERY_MS) return
  if (document.querySelector('dialog[open]')) return
  try {
    const { data, error } = await supabase.rpc('observer_final_choice_pending')
    if (error || data !== true) return
  } catch { return }
  if (document.querySelector('dialog[open]')) return
  remember(Date.now())
  open.value = true
}

watch(open, async v => {
  await nextTick()
  if (v && dialog.value && !dialog.value.open) dialog.value.showModal()
  else if (!v && dialog.value?.open) dialog.value.close()
})
watch(() => team.value?.id, () => { void check() })
onMounted(() => { window.setTimeout(() => { void check() }, 4000); timer = window.setInterval(() => { void check() }, 60_000) })
onUnmounted(() => { if (timer) window.clearInterval(timer) })

function dismiss() { remember(Date.now()); open.value = false }
function choose() { dismiss(); void router.push({ path: '/compete', hash: '#final' }) }
</script>

<template>
  <dialog v-if="open" ref="dialog" class="pinned-dialog" aria-labelledby="final-choice-title" data-testid="final-choice-reminder"
    @cancel.prevent="dismiss" @click.self="dismiss">
    <div class="pinned-panel">
      <button type="button" class="pinned-close" :aria-label="pick('Close', '关闭')" @click="dismiss">×</button>
      <h2 id="final-choice-title" class="pinned-title">{{ pick('Choose the final version', '请选定送测版本') }}</h2>
      <p class="text2 mt-3">{{ pick('The team has not chosen its final version yet. Any of the team’s confirmed versions can be chosen; the choice can no longer change after Oct 8 09:00 (UTC+8).', '本队尚未选定送测版本。送测版本可从本队任意已确认版本中选择，10 月 8 日 09:00（UTC+8）后不可再更改。') }}</p>
      <p class="text3 mt-3 text-sm">{{ pick('This reminder appears every 30 minutes until a version is chosen.', '选定前，本提醒每 30 分钟出现一次。') }}</p>
      <div class="pinned-actions">
        <button type="button" class="btn sm" data-testid="final-choice-later" @click="dismiss">{{ pick('Later', '稍后') }}</button>
        <button type="button" class="btn sm primary" data-testid="final-choice-go" @click="choose">{{ pick('Choose the final version', '去选定送测版本') }}</button>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.pinned-dialog { width: min(36rem, calc(100vw - 1.5rem)); max-height: calc(100dvh - 1.5rem); padding: 0; margin: auto;
  border: 1px solid rgba(158,173,255,.35); background: #0b1022; color: #e8ecf8; box-shadow: 0 24px 80px rgba(0,0,0,.6); }
.pinned-dialog::backdrop { background: rgba(2,5,14,.72); backdrop-filter: blur(2px); }
.pinned-panel { position: relative; padding: 1.5rem 1.4rem 1.25rem; overflow-wrap: anywhere; }
@media (min-width: 640px) { .pinned-panel { padding: 2rem 2rem 1.5rem; } }
.pinned-title { padding-right: 2rem; font-size: 1.45rem; font-weight: 600; line-height: 1.3; letter-spacing: -.02em; color: #f5f7ff; }
.pinned-close { position: absolute; top: .6rem; right: .7rem; width: 2.4rem; height: 2.4rem; font-size: 1.6rem; line-height: 1; color: #aeb6c8; background: none; border: 0; cursor: pointer; }
.pinned-actions { display: flex; justify-content: flex-end; gap: .6rem; margin-top: 1.4rem; flex-wrap: wrap; }
</style>
