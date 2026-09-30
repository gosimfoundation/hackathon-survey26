<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '../composables/useI18n'
import { usePhases } from '../composables/usePhases'
import PageHead from '../components/layout/PageHead.vue'
import PhaseTable from '../components/content/PhaseTable.vue'
import MarkdownArticle from '../components/content/MarkdownArticle.vue'
import rulesEn from '../content/rules.en.md?raw'
import rulesZh from '../content/rules.zh.md?raw'

const { t, pick } = useI18n()
const { phases, loading } = usePhases()
const source = computed(() => pick(rulesEn, rulesZh))
</script>

<template>
  <main class="poster-canvas page-read">
    <PageHead :kicker="t('rules_page.kicker')" :title="t('rules_page.title')" :note="t('rules_page.version')" />
    <section class="section tight"><div class="wrap">
      <h2 class="label accent mb-4">{{ t('rules_page.phases_title') }}</h2>
      <p v-if="loading" class="text3 text-sm">{{ t('common.loading') }}</p>
      <PhaseTable v-else :phases="phases" />
    </div></section>
    <section class="section"><div class="wrap">
      <MarkdownArticle :source="source" />
    </div></section>
  </main>
</template>
