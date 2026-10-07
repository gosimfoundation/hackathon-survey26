<script setup lang="ts">
// 选定冻结 / Freeze selection: the team captain locks the team's explicitly chosen final version before the
// deadline. Irreversible for the team (observer_freeze_final_version; the database checks the captain, the
// phase and the choice). Several confirmations: a summary with a warning, "confirmed with teammates", and the
// team name typed exactly.
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { canFreezeFinal, finalOpen, type FinalVersion } from '../../lib/projectEvaluation'
import { formatDateTime } from '../../lib/projectText'

const props = defineProps<{
  final: FinalVersion
  /** Label of the chosen version, its creation time and its best formal score (null when not evaluated). */
  label: string; createdAt: string | null; bestScore: number | null
  busy: boolean
}>()
const emit = defineEmits<{ freeze: [revisionId: string] }>()
const { pick, locale } = useI18n()
const when = (v: string | null | undefined) => formatDateTime(v, locale.value)
const open = ref(false), agreed = ref(false), typed = ref('')
const dialog = ref<HTMLDialogElement | null>(null)
const teamName = computed(() => props.final.team_name ?? '')
const ready = computed(() => agreed.value && !!teamName.value && typed.value === teamName.value && !props.busy)
const shown = computed(() => !!props.final.frozen_at || finalOpen(props.final))

watch(open, async v => {
  await nextTick()
  if (v && dialog.value && !dialog.value.open) dialog.value.showModal()
  else if (!v && dialog.value?.open) dialog.value.close()
})
function start() { agreed.value = false; typed.value = ''; open.value = true }
function close() { open.value = false }
function confirm() {
  if (!ready.value || !props.final.chosen_revision_id) return
  emit('freeze', props.final.chosen_revision_id)
  open.value = false
}
</script>

<template>
  <div v-if="shown" class="mt-3" data-testid="final-freeze">
    <p v-if="final.frozen_at" class="freeze-done" role="status" data-testid="final-freeze-done">
      <strong>{{ pick('Final version frozen ✓', '送测版本已冻结 ✓') }}</strong>（{{ when(final.frozen_at) }}）· {{ label }}
    </p>
    <template v-else>
      <p class="flex flex-wrap items-center gap-3">
        <button type="button" class="btn sm" :disabled="busy || !canFreezeFinal(final)" data-testid="final-freeze-start" @click="start">
          {{ pick('Freeze selection', '选定冻结') }}</button>
        <span class="help">{{ !final.is_captain
          ? pick('Only the team captain can freeze the final version.', '只有队长可以选定冻结送测版本。')
          : final.source !== 'chosen'
            ? pick('Choose a version below with “Set as final version” first; the default cannot be frozen.', '请先在下方点击「设为最终版本」明确选择一个版本；默认版本不能冻结。')
            : pick('Optional: lock the chosen version now. Afterwards it can no longer be changed.', '可选：现在锁定已选择的版本，之后不可再更改。') }}</span>
      </p>
    </template>
    <dialog v-if="open" ref="dialog" class="pinned-dialog" aria-labelledby="final-freeze-title" data-testid="final-freeze-dialog"
      @cancel.prevent="close" @click.self="close">
      <div class="pinned-panel">
        <button type="button" class="pinned-close" :aria-label="pick('Close', '关闭')" @click="close">×</button>
        <h2 id="final-freeze-title" class="pinned-title">{{ pick('Freeze selection', '选定冻结') }}</h2>
        <dl class="freeze-summary mt-3">
          <dt>{{ pick('Version', '版本') }}</dt><dd data-testid="final-freeze-label">{{ label }}</dd>
          <dt>{{ pick('Created', '创建时间') }}</dt><dd>{{ createdAt ? when(createdAt) : '—' }}</dd>
          <dt>{{ pick('Best score', '最高分') }}</dt><dd>{{ bestScore != null ? bestScore.toFixed(2) : pick('not evaluated yet', '尚未评测') }}</dd>
        </dl>
        <p class="errors mt-3" role="alert">{{ pick('After freezing, your team’s final version can no longer be changed. This cannot be undone.', '冻结后本队送测版本将不可再更改，此操作不可撤销。') }}</p>
        <label class="flex items-center gap-2 mt-3"><input v-model="agreed" type="checkbox" data-testid="final-freeze-agree">
          {{ pick('I have confirmed this with my teammates', '我已与队友确认') }}</label>
        <label class="block mt-3">{{ pick('Type your team name to confirm:', '请输入队伍名称以确认：') }} <strong>{{ teamName }}</strong>
          <input v-model="typed" type="text" class="freeze-input mt-1" autocomplete="off" spellcheck="false" data-testid="final-freeze-name"></label>
        <div class="pinned-actions">
          <button type="button" class="btn sm" @click="close">{{ pick('Cancel', '取消') }}</button>
          <button type="button" class="btn sm primary" :disabled="!ready" data-testid="final-freeze-confirm" @click="confirm">
            {{ pick('Confirm freeze', '确认冻结') }}</button>
        </div>
      </div>
    </dialog>
  </div>
</template>

<style scoped>
.freeze-done { padding: .6rem .8rem; border: 1px solid rgba(74,222,128,.45); background: rgba(74,222,128,.08); }
.freeze-summary { display: grid; grid-template-columns: auto 1fr; gap: .3rem 1rem; }
.freeze-summary dt { color: #aeb6c8; }
.freeze-input { width: 100%; padding: .45rem .6rem; background: rgba(255,255,255,.05); border: 1px solid rgba(158,173,255,.35); color: inherit; }
.pinned-dialog { width: min(36rem, calc(100vw - 1.5rem)); max-height: calc(100dvh - 1.5rem); padding: 0; margin: auto;
  border: 1px solid rgba(158,173,255,.35); background: #0b1022; color: #e8ecf8; box-shadow: 0 24px 80px rgba(0,0,0,.6); }
.pinned-dialog::backdrop { background: rgba(2,5,14,.72); backdrop-filter: blur(2px); }
.pinned-panel { position: relative; padding: 1.5rem 1.4rem 1.25rem; overflow-wrap: anywhere; }
@media (min-width: 640px) { .pinned-panel { padding: 2rem 2rem 1.5rem; } }
.pinned-title { padding-right: 2rem; font-size: 1.45rem; font-weight: 600; line-height: 1.3; letter-spacing: -.02em; color: #f5f7ff; }
.pinned-close { position: absolute; top: .6rem; right: .7rem; width: 2.4rem; height: 2.4rem; font-size: 1.6rem; line-height: 1; color: #aeb6c8; background: none; border: 0; cursor: pointer; }
.pinned-close:hover { color: #fff; }
.pinned-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: .75rem; margin-top: 1.5rem; }
</style>
