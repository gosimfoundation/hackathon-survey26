<script setup lang="ts">
import { useI18n } from '../../composables/useI18n'
import { fmtUtc } from '../../lib/format'
import type { Phase } from '../../lib/data'
import StatusPill from '../layout/StatusPill.vue'
defineProps<{ phases: Phase[]; compact?: boolean }>()
const { t, pick } = useI18n()
// Unknown modes fall back to the stored value rather than an i18n key path.
const boardMode = (mode: string) => { const key = 'rules_page.board_modes.' + mode, text = t(key); return text === key ? mode : text }
function submissions(p: Phase) {
  const s = p.observer_settings
  if (s?.projects_enabled || s?.local_sessions_enabled) return [
    ...(s.projects_enabled ? [pick('Complete project', '完整项目')] : []),
    ...(s.local_sessions_enabled ? [pick('Local-session CSV', '本地会话 CSV')] : []),
  ].join(' / ')
  return p.allow_results ? 'decisions.csv' : t('common.no')
}
</script>

<template>
  <div class="table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th>{{ t('leaderboard.phase') }}</th><th>{{ t('common.status') }}</th><th>{{ t('common.utc') }}</th>
          <template v-if="!compact"><th>{{ pick('Submissions', '提交方式') }}</th></template>
          <th class="r">{{ t('rules_page.daily') }}</th>
          <th v-if="!compact">{{ t('rules_page.board') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="p in phases" :key="p.id" data-testid="phase-row" :data-phase="p.slug">
          <td>{{ pick(p.name_en, p.name_zh) }}</td>
          <td><StatusPill :status="p.status" ns="leaderboard.status" /></td>
          <td class="m xs whitespace-nowrap">{{ fmtUtc(p.starts_at, { short: compact }) }} → {{ fmtUtc(p.ends_at, { short: compact }) }}</td>
          <template v-if="!compact"><td>{{ submissions(p) }}</td></template>
          <td class="r m">{{ p.observer_settings?.projects_enabled || p.observer_settings?.local_sessions_enabled ? p.observer_settings.daily_batches : p.daily_limit }}</td>
          <td v-if="!compact" class="m xs">{{ boardMode(p.leaderboard_mode) }}</td>
        </tr>
        <tr v-if="!phases.length"><td :colspan="compact ? 4 : 6" class="text3">{{ t('leaderboard.no_phases') }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
