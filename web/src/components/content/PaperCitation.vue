<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { PAPER } from '../../content/paper/citation'

const { t } = useI18n()
const copied = ref(false)
async function copyBibtex() {
  try {
    await navigator.clipboard.writeText(PAPER.bibtex)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* clipboard blocked: the BibTeX stays selectable below */ }
}
</script>

<template>
  <article class="card paper-card" data-testid="paper-citation">
    <span class="label accent">arXiv:{{ PAPER.arxivId }}</span>
    <h3 class="mt-3">{{ PAPER.title }}</h3>
    <p class="paper-authors">{{ PAPER.authors }}</p>
    <p class="paper-actions">
      <a class="btn primary sm" :href="PAPER.absUrl" target="_blank" rel="noopener">{{ t('paper.open_arxiv') }} ↗</a>
      <a class="btn sm" :href="PAPER.pdfUrl" target="_blank" rel="noopener">PDF ↗</a>
      <button type="button" class="btn sm" data-testid="paper-copy-bibtex" @click="copyBibtex">{{ copied ? t('paper.copied') : t('paper.copy_bibtex') }}</button>
    </p>
    <details class="paper-bibtex">
      <summary>BibTeX</summary>
      <pre>{{ PAPER.bibtex }}</pre>
    </details>
  </article>
</template>

<style scoped>
.paper-card h3 { font-size: 1.05rem; line-height: 1.4; color: #f5f7ff; }
.paper-authors { margin-top: .4rem; font-size: .85rem; color: #aeb6c8; }
.paper-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1rem; }
.paper-bibtex { margin-top: 1rem; font-size: .8rem; color: #aeb6c8; }
.paper-bibtex summary { cursor: pointer; }
.paper-bibtex pre { margin-top: .5rem; padding: .8rem 1rem; overflow-x: auto; background: rgba(5,7,15,.7); border: 1px solid rgba(158,173,255,.22); color: #dfe4ff; font-size: .75rem; line-height: 1.5; white-space: pre; }
</style>
