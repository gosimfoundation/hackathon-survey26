<script setup lang="ts">
// One line under the hero actions: organizer and sponsor (linking to their sites) and the scientific committee (linking to /about).
import { useI18n } from '../../composables/useI18n'
import { appUrl } from '../../composables/api'
import { useOrganizers } from '../../composables/useOrganizers'

const { t } = useI18n()
const { items, logo, wordmark, site } = useOrganizers()
</script>

<template>
  <div class="hero-credits" data-testid="hero-credits" :aria-label="t('home.credits.aria')" role="group">
    <a v-for="item in items" :key="item.name" class="hero-credit" :href="site(item.name) || undefined" target="_blank" rel="noopener">
      <span class="hero-credit-role">{{ item.role }}</span>
      <img v-if="logo(item.name)" :src="logo(item.name)" :alt="wordmark(item.name) ? item.name : ''" :title="item.name" class="hero-credit-logo" :class="{ wordmark: wordmark(item.name) }">
      <b v-if="!wordmark(item.name)">{{ item.name }}</b>
    </a>
    <a class="hero-credit" href="https://github.com/octos-org/" target="_blank" rel="noopener" data-testid="hero-credits-octos">
      <span class="hero-credit-role">{{ t('home.credibility.octos.kicker') }}</span>
      <img :src="appUrl('media/octos-logo.webp')" :alt="t('home.credibility.octos.logoAlt')" class="hero-credit-logo wordmark">
      <b>Octos</b>
    </a>
    <router-link :to="{ path: '/about', hash: '#committee' }" class="hero-credit hero-credit-committee" data-testid="hero-credits-all">
      <b>{{ t('home.credibility.committee.kicker') }}</b><span aria-hidden="true">→</span>
    </router-link>
  </div>
</template>

<style scoped>
.hero-credits {
  display: flex; flex-wrap: wrap; align-items: center; gap: .6rem 2rem;
  font-size: 1.05rem; line-height: 1.4; color: rgba(226,234,255,.9);
}
.hero-credit {
  display: inline-flex; align-items: center; gap: .6rem; min-width: 0;
  color: inherit; text-decoration: none; transition: opacity .2s ease;
}
a.hero-credit:hover { opacity: .8; }
.hero-credit:focus-visible { outline: 1px solid #78a6ff; outline-offset: 4px; }
.hero-credit-role {
  font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .74rem;
  letter-spacing: .12em; text-transform: uppercase; color: rgba(255,255,255,.6);
}
.hero-credit b { font-weight: 650; font-size: 1.15rem; color: #f5f7ff; letter-spacing: .01em; }
.hero-credit-logo { height: 28px; width: 28px; }
.hero-credit-logo.wordmark { height: 24px; width: auto; }
.hero-credit-committee b { color: #f5f7ff; }
.hero-credit-committee span { color: #78a6ff; font-size: 1.1rem; }
.hero-credit-committee:hover span { color: #f7f9ff; }
</style>
