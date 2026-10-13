/**
 * Open track for the new AOH tasks (migration 20261013000000_open_track, workers in open_track/).
 * API calls through the shared Supabase client; rules and helpers live in openTrackRules.ts.
 */
import { supabase } from './supabase'
import executorKeyJson from './executorKey.json'
import { encryptKey, executorKeyFrom, keyHint, toBase64, type ModelChoice, type OpenBoardRow, type OpenProblem, type OpenScore, type OpenSubmission } from './openTrackRules'

export * from './openTrackRules'

/** Pinned in the bundle: swapping a static file on the site cannot redirect participants' keys. */
export const executorKey: JsonWebKey | null = executorKeyFrom(executorKeyJson)

export async function listProblems(): Promise<OpenProblem[]> {
  const { data, error } = await supabase.from('open_problems').select('id,title_zh,title_en,version,seed_indices,kit_url,sort').eq('active', true).order('sort')
  if (error) throw error
  return (data ?? []) as OpenProblem[]
}

export async function submit(problems: string[], zip: Uint8Array, model: ModelChoice | null, jwk: JsonWebKey | null, note = ''): Promise<string> {
  let cipher = ''
  if (model) {
    if (!jwk) throw new Error('model_unavailable')
    cipher = await encryptKey(jwk, model.key)
  }
  const { data, error } = await supabase.rpc('open_submit', {
    p_problems: problems, p_zip_base64: toBase64(zip),
    p_model_base: model?.base ?? '', p_model_name: model?.model ?? '',
    p_key_ciphertext: cipher, p_key_hint: model ? keyHint(model.key) : '', p_note: note,
  })
  if (error) throw error
  return data as string
}

export async function mySubmissions(): Promise<{ subs: OpenSubmission[]; scores: OpenScore[] }> {
  const [s, c] = await Promise.all([
    supabase.from('open_submissions').select('id,problems,status,uses_model,model_name,key_hint,note,created_at').order('created_at', { ascending: false }).limit(50),
    supabase.from('open_submission_scores').select('submission_id,problem_id,seeds,seeds_done,mean_total'),
  ])
  if (s.error) throw s.error
  if (c.error) throw c.error
  return { subs: (s.data ?? []) as OpenSubmission[], scores: (c.data ?? []) as OpenScore[] }
}

export async function cancel(id: string): Promise<void> {
  const { error } = await supabase.rpc('open_cancel', { p_submission: id })
  if (error) throw error
}

export async function leaderboard(): Promise<OpenBoardRow[]> {
  const { data, error } = await supabase.rpc('open_leaderboard')
  if (error) throw error
  return (data ?? []) as OpenBoardRow[]
}
