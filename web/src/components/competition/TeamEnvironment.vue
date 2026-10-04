<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { portal, type TeamEnvironment } from '../../lib/observerPortal'

// Keys and network: the team's variables (environment of its program) and the
// domains the program may reach on port 443. Secret values are write-only here.
const props = defineProps<{ environment: TeamEnvironment | null | undefined; busy: boolean }>()
const emit = defineEmits<{ act: [work: () => Promise<void>, success: string] }>()
const { t, tf } = useI18n()
const variables = computed(() => props.environment?.variables ?? [])
const domains = computed(() => props.environment?.domains ?? [])
const limits = computed(() => props.environment?.limits ?? { variables: 20, domains: 10, value_bytes: 8192 })
const form = ref({ name: '', value: '', secret: true })
const domain = ref('')

function saveVariable() {
  const body = { name: form.value.name.trim().toUpperCase(), value: form.value.value, secret: form.value.secret }
  // The value never stays in the page once it has been sent.
  form.value.value = ''
  emit('act', async () => { await portal('save_team_variable', body); form.value.name = ''; form.value.secret = true },
    t('submit.team_env.saved'))
}
function deleteVariable(name: string) {
  emit('act', async () => { await portal('delete_team_variable', { name }) }, t('submit.team_env.deleted'))
}
function setDomains(list: string[], clear = false) {
  emit('act', async () => { await portal('set_team_domains', { domains: list }); if (clear) domain.value = '' },
    t('submit.team_env.domains_saved'))
}
function addDomain() {
  const host = domain.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[/:].*$/, '')
  if (host && !domains.value.includes(host)) setDomains([...domains.value, host], true)
}
</script>

<template>
  <div data-testid="team-environment">
    <p class="help mt-3">{{ t('submit.team_env.intro') }}</p>
    <p v-if="environment?.relay_key_missing" class="errors" role="alert" data-testid="team-env-relay-banner">{{ t('submit.team_env.relay_banner') }}</p>
    <p class="help" data-testid="team-env-final-note">{{ t('submit.team_env.final_note') }}</p>

    <h3 class="mt-4">{{ t('submit.team_env.vars_title') }}</h3>
    <p class="help">{{ tf('submit.team_env.vars_help', { variables: limits.variables }) }}</p>
    <ul v-if="variables.length" class="team-env-list" data-testid="team-env-variables">
      <li v-for="v in variables" :key="v.name">
        <code>{{ v.name }}</code>
        <span class="help break-all">{{ v.secret ? (v.hint ? tf('submit.model_api.key_ending', { hint: v.hint }) : t('submit.model_api.key_hidden')) : v.value }}</span>
        <button type="button" class="btn sm" :disabled="busy" :data-testid="'team-env-delete-' + v.name" @click="deleteVariable(v.name)">{{ t('submit.team_env.delete') }}</button>
      </li>
    </ul>
    <p v-else class="help">{{ t('submit.team_env.no_variables') }}</p>
    <form class="mt-3" autocomplete="off" data-testid="team-env-variable-form" @submit.prevent="saveVariable">
      <label class="field"><span>{{ t('submit.team_env.name') }}</span><input v-model="form.name" type="text" name="observer-variable-name" required maxlength="64" pattern="[A-Za-z][A-Za-z0-9_]{0,63}" placeholder="OPENAI_API_KEY" autocomplete="off" spellcheck="false" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" data-testid="team-env-name"></label>
      <label class="field"><span>{{ t('submit.team_env.value') }}</span><input v-model="form.value" :type="form.secret ? 'password' : 'text'" name="observer-variable-value" required maxlength="8192" autocomplete="new-password" spellcheck="false" data-lpignore="true" data-1p-ignore="true" data-bwignore="true" data-form-type="other" data-testid="team-env-value"></label>
      <label class="check"><input v-model="form.secret" type="checkbox" name="observer-variable-secret" data-testid="team-env-secret">{{ t('submit.team_env.secret') }}</label>
      <p><button class="btn sm" :disabled="busy || variables.length >= limits.variables && !variables.some(v => v.name === form.name.trim().toUpperCase())" data-testid="team-env-save">{{ t('submit.team_env.save') }}</button></p>
    </form>

    <h3 class="mt-4">{{ t('submit.team_env.domains_title') }}</h3>
    <p class="help">{{ tf('submit.team_env.domains_help', { domains: limits.domains }) }}</p>
    <ul v-if="domains.length" class="team-env-list" data-testid="team-env-domains">
      <li v-for="host in domains" :key="host">
        <code>{{ host }}</code>
        <button type="button" class="btn sm" :disabled="busy" :data-testid="'team-env-remove-' + host" @click="setDomains(domains.filter(d => d !== host))">{{ t('submit.team_env.remove') }}</button>
      </li>
    </ul>
    <p v-else class="help">{{ t('submit.team_env.no_domains') }}</p>
    <form class="mt-3" autocomplete="off" data-testid="team-env-domain-form" @submit.prevent="addDomain">
      <label class="field"><span>{{ t('submit.team_env.domain') }}</span><input v-model="domain" type="text" name="observer-domain" required maxlength="253" placeholder="api.kimi.com" autocomplete="off" spellcheck="false" data-testid="team-env-domain"></label>
      <p><button class="btn sm" :disabled="busy || domains.length >= limits.domains" data-testid="team-env-add-domain">{{ t('submit.team_env.add_domain') }}</button></p>
    </form>
    <p class="help mt-3">{{ t('submit.team_env.proxy_note') }}</p>
  </div>
</template>

<style scoped>
.team-env-list { list-style: none; padding: 0; margin: .5rem 0; display: grid; gap: .4rem; }
.team-env-list li { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; }
.team-env-list code { font-weight: 600; }
</style>
