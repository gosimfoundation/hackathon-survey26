import { reactive, readonly } from 'vue'
import { isSupabaseConfigured, supabase } from '../lib/supabase'
const state = reactive({ mode: 'practice' as 'practice'|'competition', phaseId: null as string|null, betaPhaseId: null as string|null, projectPhaseId: null as string|null })
let fetched = 0, pending: Promise<void>|null = null
export const competition = readonly(state)
export async function loadCompetition(force=false) {
  if (pending) { await pending; if (!force) return state }
  if (!force && Date.now()-fetched<15000) return state
  pending=(async () => {
    if (!isSupabaseConfigured) return
    const {data,error}=await supabase.rpc('current_competition')
    if (!error && data) {
      state.mode=data.mode==='competition'?'competition':'practice'
      state.phaseId=typeof data.phase_id==='string'?data.phase_id:null
      // Practice only: the separate complete-project board next to CSV practice.
      state.projectPhaseId=typeof data.project_phase_id==='string'?data.project_phase_id:null
      fetched=Date.now()
    }
    // Team-restricted beta entry: the RPC is granted to signed-in users only and
    // answers with a phase just for its access team. The
    // previous value stays until the fresh answer avoids entry flicker.
    let beta: string|null = null
    const {data:{session}}=await supabase.auth.getSession()
    if (session) {
      const answer=await supabase.rpc('my_observer_phase')
      if (!answer.error && typeof answer.data==='string') beta=answer.data
    }
    state.betaPhaseId=beta
  })()
  try { await pending } finally { pending=null }
  return state
}
