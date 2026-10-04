<script setup lang="ts">
// One quiet line under the hero actions: organizer, sponsor and the scientific committee, linking to /about.
import { computed } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { useOrganizers } from '../../composables/useOrganizers'
import { committeePreview } from '../../lib/organizers'

const { t, tf } = useI18n()
const { items, committee, logo, wordmark } = useOrganizers()
const preview = computed(() => committeePreview(committee.value))
const committeeLine = computed(() => tf('home.credits.committee_names', {
  names: preview.value.names.join(t('home.credits.name_sep')),
  more: preview.value.more,
  total: preview.value.total,
}))
</script>

<template>
  <div class="hero-credits" data-testid="hero-credits" :aria-label="t('home.credits.aria')" role="group">
    <span v-for="item in items" :key="item.name" class="hero-credit">
      <span class="hero-credit-role">{{ item.role }}</span>
      <img v-if="logo(item.name)" :src="logo(item.name)" :alt="wordmark(item.name) ? item.name : ''" :title="item.name" class="hero-credit-logo" :class="{ wordmark: wordmark(item.name) }">
      <b v-if="!wordmark(item.name)">{{ item.name }}</b>
    </span>
    <span class="hero-credit">
      <span class="hero-credit-role">{{ t('home.credibility.committee.kicker') }}</span>
      <span class="hero-credit-names">{{ committeeLine }}</span>
    </span>
    <router-link to="/about" class="hero-credit-all" data-testid="hero-credits-all">{{ t('home.credits.all') }} →</router-link>
  </div>
</template>

<style scoped>
.hero-credits {
  display: flex; flex-wrap: wrap; align-items: center; gap: .45rem 1.25rem;
  font-size: .82rem; line-height: 1.5; color: rgba(226,234,255,.78);
}
.hero-credit { display: inline-flex; flex-wrap: wrap; align-items: center; gap: .2rem .5rem; min-width: 0; }
.hero-credit-role {
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .64rem;
  letter-spacing: .12em; text-transform: uppercase; color: rgba(255,255,255,.5);
}
.hero-credit b { font-weight: 600; color: #f5f7ff; }
.hero-credit-logo { height: 18px; width: 18px; }
.hero-credit-logo.wordmark { height: 15px; width: auto; }
.hero-credit-names { color: rgba(226,234,255,.86); }
.hero-credit-all {
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .7rem; letter-spacing: .08em;
  color: #78a6ff; white-space: nowrap; transition: color .2s ease;
}
.hero-credit-all:hover { color: #f7f9ff; }
.hero-credit-all:focus-visible { outline: 1px solid #78a6ff; outline-offset: 3px; }
</style>
