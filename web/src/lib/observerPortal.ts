import { supabase } from './supabase'
import type { EvaluationQuota, FinalVersion } from './projectEvaluation'

export type ProjectRevision = {
  id: string; status: string; source_kind: string; source_location: string; source_digest: string | null
  approval_digest: string | null; manifest: Record<string, unknown> | null; adapter_files: Record<string, string>
  explanation: string; error: string; public_test: { passed?: boolean; summary?: string; run_id?: string; status?: string }
  observer_evidence: { notes: string; code_url: string } | null
  created_at: string; approved_at?: string | null; archived_at?: string | null
}
/** The team's model key choice; a saved key is described, never returned. */
export type TeamModel = {
  mode: 'stored' | 'relay'
  saved: { base_url: string; model: string; key_hint: string; saved_at: string } | null
}
export type PortalData = {
  phases: { phase_id: string; projects_enabled: boolean; local_sessions_enabled: boolean; daily_batches: number
    model_token_limit: number; model_call_limit: number; model_concurrency: number; phases: { slug: string; name_en: string; name_zh: string; is_active: boolean
      starts_at: string | null; ends_at: string | null } }[]
  projects: { id: string; title: string; created_at: string; observer_revisions: ProjectRevision[] }[]
  batches: { id: string; mode: string; status: string; score: number | null; created_at: string
    phase_id: string; revision_id: string | null; quota_refunded?: boolean
    observer_runs: { id: string; status: string; score: number | null; result_path: string | null
      score_summary?: { raw_score?: { total: number }; calibration?: { version: string } } | null }[] }[]
  providers: { id: string; name: string; base_url: string; models: string[]; shared: boolean; enabled: boolean; daily_token_limit: number }[]
  team_model: TeamModel | null
  model_bases: string[]
  /** Missing until the database provides it; the database enforces the limit either way. */
  quota?: EvaluationQuota[] | null
  /** The team's final version per open formal phase; missing until the database provides it. */
  final_versions?: FinalVersion[] | null
}

export async function portal<T>(action: string, fields: Record<string, unknown> = {}): Promise<T> {
  const { data, error } = await supabase.functions.invoke('observer-portal', { body: { action, ...fields } })
  if (error) {
    let code = 'portal_unavailable'
    if (error.context instanceof Response) {
      try { code = (await error.context.clone().json()).error ?? code } catch { /* safe generic error */ }
    }
    throw new Error(code)
  }
  if (data?.error) throw new Error(data.error)
  return data.data as T
}

export async function uploadProjectFile(file: File, purpose: 'source' | 'csv') {
  const ext = purpose === 'source' ? '.zip' : '.csv'
  if (!file.name.toLowerCase().endsWith(ext)) throw new Error('wrong_file_type')
  if (!file.size || file.size > (purpose === 'source' ? 50 : 20) * 1024 * 1024) throw new Error('file_too_large')
  const slot = await portal<{ id: string; path: string; token: string }>('upload', { purpose })
  const { error } = await supabase.storage.from('observer-staging').uploadToSignedUrl(slot.path, slot.token, file, {
    contentType: purpose === 'source' ? 'application/zip' : 'text/csv',
  })
  if (error) throw new Error('upload_failed')
  return slot.id
}
