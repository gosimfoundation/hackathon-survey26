<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { useFinalProgress, type FinalCardState } from '../../composables/useFinalProgress'

/** Hidden-final progress: overall counts, or (mine) the visitor's own team's cards. Never scores. */
const props = withDefaults(defineProps<{ tone?: 'dark' | 'light', mine?: boolean }>(), { tone: 'light', mine: false })
const { pick } = useI18n()
const { progress } = useFinalProgress()
const n = (v: number) => v.toLocaleString('en-US')
const share = computed(() => progress.value && progress.value.runs_total > 0 ? Math.min(1, progress.value.runs_done / progress.value.runs_total) : 0)
const stateLabel = (s: FinalCardState) => s === 'done' ? pick('done', '已完成') : s === 'running' ? pick('running', '进行中') : pick('waiting', '等待')
</script>

<template>
  <div v-if="progress && !props.mine" class="final-progress" :class="`is-${props.tone}`" role="status" data-testid="final-progress">
    <p>{{ pick(`Evaluations finished: ${n(progress.runs_done)} / ${n(progress.runs_total)} · Teams finished: ${n(progress.teams_done)} / ${n(progress.teams_total)}`, `已完成评测 ${n(progress.runs_done)} / ${n(progress.runs_total)} 次 · 已跑完 ${n(progress.teams_done)} / ${n(progress.teams_total)} 队`) }}</p>
    <progress :value="share" max="1" :aria-label="pick('Hidden-card evaluation progress', '隐藏卡评测进度')"></progress>
  </div>
  <p v-else-if="progress?.my_cards?.length && props.mine" class="final-progress-mine help mt-2" role="status" data-testid="final-progress-mine">
    {{ pick('Your team: ', '本队进度：') }}<template v-for="(c, i) in progress.my_cards" :key="c.card"><span v-if="i"> · </span><b>{{ c.card }}</b> <span :class="`is-${c.state}`">{{ stateLabel(c.state) }}</span></template>
  </p>
</template>

<style scoped>
.final-progress p { margin: .35rem 0 0; font-size: .82rem; font-variant-numeric: tabular-nums; }
.final-progress progress { display: block; width: 100%; max-width: 28rem; height: .4rem; margin-top: .4rem; accent-color: #315efb; }
.final-progress.is-dark p { color: rgba(255,255,255,.72); }
.final-progress.is-dark progress { accent-color: #78a6ff; }
.final-progress-mine .is-done { color: #1a7f37; }
.final-progress-mine .is-running { color: #315efb; }
</style>
