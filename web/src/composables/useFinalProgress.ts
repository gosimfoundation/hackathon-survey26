import { onMounted, onUnmounted, ref } from 'vue'
import { isSupabaseConfigured, supabase } from '../lib/supabase'

export type FinalCardState = 'done' | 'running' | 'waiting'
export interface FinalProgress {
  teams_total: number
  teams_done: number
  runs_total: number
  runs_done: number
  runs_running: number
  my_cards?: { card: string, state: FinalCardState }[] | null
}

// One shared fetch for every progress line on the page; the database shares the counts for 30 s.
const progress = ref<FinalProgress | null>(null)
let users = 0
let timer: number | undefined

async function refresh() {
  if (!isSupabaseConfigured) return
  try {
    const { data, error } = await supabase.rpc('observer_final_progress')
    if (!error) progress.value = (data ?? null) as FinalProgress | null
  } catch { /* progress is informational: keep the last value */ }
}

/** Hidden-final progress (counts only, never scores), refreshed once a minute while shown. */
export function useFinalProgress() {
  onMounted(() => {
    if (users++ === 0) { void refresh(); timer = window.setInterval(refresh, 60_000) }
  })
  onUnmounted(() => {
    if (--users === 0 && timer) { window.clearInterval(timer); timer = undefined }
  })
  return { progress }
}
