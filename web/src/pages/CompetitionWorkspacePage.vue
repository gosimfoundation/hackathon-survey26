<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { loadCompeteUiSetting, loadPhases,type Phase } from '../lib/data'
import { COMPETE_UI_STORAGE, competeLayout, layoutOverride, type CompeteLayout } from '../lib/competeUi'
import { competition, loadCompetition } from '../stores/competition'
import { useAuth } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import DashShell from '../components/layout/DashShell.vue'
import ProjectWorkflow from '../components/competition/ProjectWorkflow.vue'
import SoloTeamButton from '../components/SoloTeamButton.vue'
import TeamInbox from '../components/TeamInbox.vue'
const {t,pick}=useI18n(),{team,refreshMe}=useAuth()
const phase=ref<Phase|null>(null),loading=ref(true),failed=ref(false),layout=ref<CompeteLayout>('classic')
// The header names the phase this page evaluates in: the workflow reports the one it binds to; until then the
// first phase that has not ended, in the workflow's order (beta entry, complete-project board, global phase).
const kickerPhase=ref<Phase|null>(null),workflowPhase=ref<{name_en:string;name_zh:string}|null>(null)
const kicker=computed(()=>{const p=workflowPhase.value??kickerPhase.value??phase.value;return p?pick(p.name_en,p.name_zh):''})
// Simplified layout behind a switch (site_settings 'event'.compete_ui); ?ui=v2|v1|auto overrides it for this browser.
async function chooseLayout(){
  const query=new URLSearchParams(location.search).get('ui')
  let remembered:string|null=null
  try{
    if(query==='auto')localStorage.removeItem(COMPETE_UI_STORAGE)
    else if(query==='v2'||query==='v1')localStorage.setItem(COMPETE_UI_STORAGE,query)
    remembered=localStorage.getItem(COMPETE_UI_STORAGE)
  }catch{/* storage blocked: the switch alone decides */}
  const override=layoutOverride(query,remembered)
  layout.value=competeLayout(override?{v2_all:false,v2_teams:[]}:await loadCompeteUiSetting(),team.value?.id,override)
}
onMounted(async()=>{try{await refreshMe()
  await chooseLayout()
  // Team or membership changes do not raise auth events, so the workspace always
  // re-resolves the beta entry fresh instead of trusting the 15s cache.
  await loadCompetition(true)
  // Public pages keep the single global phase; this workspace alone swaps in the
  // team-restricted beta entry for its access team.
  const phases=await loadPhases(true)
  const global=phases.find(p=>competition.phaseId?p.id===competition.phaseId:p.slug===(competition.mode==='practice'?'practice':'online'))
  phase.value=phases.find(p=>p.id===competition.betaPhaseId)??global??null
  const open=(p:Phase|undefined)=>!!p&&p.is_active!==false&&(!p.ends_at||Date.parse(p.ends_at)>Date.now())
  kickerPhase.value=[competition.betaPhaseId,competition.projectPhaseId,global?.id].map(id=>phases.find(p=>p.id===id)).find(open)??phase.value
}catch{failed.value=true}finally{loading.value=false}})
</script>
<template>
  <DashShell :kicker="kicker" :title="pick('Participate','参赛')">
    <!-- Join requests and invitations waiting for an answer: shown here too so a captain cannot miss them. -->
    <TeamInbox compact class="mt-6" @changed="refreshMe" />
    <p v-if="loading" role="status">{{ t('common.loading') }}</p>
    <p v-else-if="failed" role="alert">{{ pick('Could not load the competition. Please refresh.','比赛信息加载失败，请刷新重试。') }}</p>
    <div v-else-if="!team" class="panel"><p>{{ t('submit.errors.need_team') }}</p><p class="mt-5 actions-inline"><router-link class="btn primary sm" to="/team">{{ t('nav.team') }} →</router-link><SoloTeamButton /></p></div>
    <p v-else-if="!phase" class="panel">{{ pick('No competition is available yet.','当前还没有开放的比赛。') }}</p>
    <ProjectWorkflow v-else :layout="layout" @phase="p => workflowPhase = p" />
  </DashShell>
</template>
