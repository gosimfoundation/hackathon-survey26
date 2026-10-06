import { supabase } from './supabase'

/** 取消排队: cancels the evaluation (and, in a self-check, its members that have not started); returns the ids cancelled. */
export async function cancelEvaluation(batchId: string): Promise<string[]> {
  const { data, error } = await supabase.rpc('observer_cancel_batch', { p_batch: batchId })
  if (error) throw new Error(error.message)
  return ((data as { cancelled?: string[] } | null)?.cancelled ?? []).map(String)
}

/** 停止评测: stops a started evaluation (its unfinished cards are cancelled, not refunded); returns its new status. */
export async function stopEvaluation(batchId: string): Promise<string> {
  const { data, error } = await supabase.rpc('observer_cancel_batch', { p_batch: batchId, p_running: true })
  if (error) throw new Error(error.message)
  return String((data as { status?: string } | null)?.status ?? '')
}
