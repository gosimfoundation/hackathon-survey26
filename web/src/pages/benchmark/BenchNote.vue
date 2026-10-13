<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useI18n } from '../../composables/useI18n'
import { setSiteView } from '../../composables/useView'

const { pick } = useI18n()
const router = useRouter()
function back() { setSiteView('competition'); router.push('/') }
</script>

<template>
  <p class="bench-note" data-testid="bench-note">
    {{ pick('You are trying the benchmark view of this site. The hackathon site is unchanged in the competition view.', '你正在试用本站的"基准视图"。黑客松网站在"比赛视图"里原样保留。') }}
    <button type="button" class="bench-note-btn" data-testid="bench-note-back" @click="back">{{ pick('Back to the competition view', '回到比赛视图') }}</button>
  </p>
</template>

<style scoped>
.bench-note { border: 1px solid rgba(120,166,255,.35); background: rgba(49,94,251,.08); padding: .75rem 1rem; color: #ccd4e6; font-size: .875rem; line-height: 1.7; }
.bench-note-btn { margin-left: .5rem; color: #78a6ff; text-decoration: underline; cursor: pointer; }
</style>
