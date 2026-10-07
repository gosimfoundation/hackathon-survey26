<script setup lang="ts">
// One friendly, actionable line next to a failure (see lib/failureHint.ts).
import { RouterLink } from 'vue-router'
import { useI18n } from '../../composables/useI18n'
import type { FailureHint } from '../../lib/failureHint'

defineProps<{ hint: FailureHint }>()
const { pick } = useI18n()
</script>

<template>
  <p class="failure-hint" role="note" data-testid="failure-hint" :data-hint="hint.id">
    <strong>{{ pick('Tip: ', '提示：') }}</strong>{{ pick(hint.en, hint.zh) }}
    <RouterLink v-if="hint.link" :to="pick(hint.link.href.en, hint.link.href.zh)" class="accent-l">{{ pick(hint.link.en, hint.link.zh) }} →</RouterLink>
  </p>
</template>

<style scoped>
.failure-hint { margin-top: .4rem; padding: .5rem .7rem; border-left: 3px solid #f5c542; background: rgba(245, 197, 66, .08); font-size: .85rem; line-height: 1.5; color: #e8e8e8; }
.failure-hint a { margin-left: .35rem; white-space: nowrap; }
</style>
