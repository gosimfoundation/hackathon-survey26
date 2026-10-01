<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { loadPhases,type Phase } from '../lib/data'
import { competition, loadCompetition } from '../stores/competition'
import { useAuth } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import DashShell from '../components/layout/DashShell.vue'
import CsvResultUpload from '../components/competition/CsvResultUpload.vue'
import ProjectWorkflow from '../components/competition/ProjectWorkflow.vue'
import SoloTeamButton from '../components/SoloTeamButton.vue'
const {t,pick}=useI18n(),{team,refreshMe}=useAuth()
const phase=ref<Phase|null>(null),projectPhase=ref<Phase|null>(null),loading=ref(true),failed=ref(false)
// Playground with a complete-project board: participants choose a complete project (default) or the legacy CSV upload.
const track=ref<'csv'|'project'>('project')
// The current phase and its database settings decide the available workflow.
const interactive=computed(()=>phase.value?.observer_settings?.projects_enabled||phase.value?.observer_settings?.local_sessions_enabled)
onMounted(async()=>{try{await refreshMe()
  // Team or membership changes do not raise auth events, so the workspace always
  // re-resolves the beta entry fresh instead of trusting the 15s cache.
  await loadCompetition(true)
  // Public pages keep the single global phase; this workspace alone swaps in the
  // team-restricted beta entry for its access team.
  const phases=await loadPhases(true)
  const global=phases.find(p=>competition.phaseId?p.id===competition.phaseId:p.slug===(competition.mode==='practice'?'practice':'online'))
  phase.value=phases.find(p=>p.id===competition.betaPhaseId)??global??null
  projectPhase.value=competition.betaPhaseId?null:phases.find(p=>p.id===competition.projectPhaseId&&p.is_active)??null
  const wanted=new URLSearchParams(location.search).get('track')
  if(projectPhase.value&&(wanted==='project'||wanted==='csv'))track.value=wanted
}catch{failed.value=true}finally{loading.value=false}})
</script>
<template>
  <DashShell :kicker="phase?pick(phase.name_en,phase.name_zh):''" :title="pick('Participate','参赛')">
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="failed" role="alert">{{ pick('Could not load the competition. Please refresh.','比赛信息加载失败，请刷新重试。') }}</p>
    <div v-else-if="!team" class="panel"><p>{{ t('submit.errors.need_team') }}</p><p class="mt-5 actions-inline"><router-link class="btn primary sm" to="/team">{{ t('nav.team') }} →</router-link><SoloTeamButton /></p></div>
    <p v-else-if="!phase" class="panel">{{ pick('No competition is available yet.','当前还没有开放的比赛。') }}</p>
    <ProjectWorkflow v-else-if="interactive" />
    <template v-else-if="projectPhase">
      <div class="panel mb-6" data-testid="practice-track">
        <p class="text2 text-sm">{{ t('submit.track.lede') }}</p>
        <div class="tabs mt-4" role="tablist">
          <button type="button" role="tab" :aria-selected="track==='csv'" :class="{ active: track==='csv' }" data-testid="track-csv" @click="track='csv'">{{ t('submit.track.csv') }}</button>
          <button type="button" role="tab" :aria-selected="track==='project'" :class="{ active: track==='project' }" data-testid="track-project" @click="track='project'">{{ t('submit.track.project') }}</button>
        </div>
        <p class="help mt-3">{{ track==='csv' ? t('submit.track.csv_help') : t('submit.track.project_help') }}</p>
      </div>
      <ProjectWorkflow v-if="track==='project'" />
      <CsvResultUpload v-else :phase="phase" />
    </template>
    <CsvResultUpload v-else :phase="phase" />
  </DashShell>
</template>
