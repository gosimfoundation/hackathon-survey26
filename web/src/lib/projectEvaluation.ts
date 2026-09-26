/** Complete-project evaluation rules shown on the project and records pages. The database enforces them. */
export type EvaluationQuota = { phase_id: string; daily_batches: number; used: number; remaining: number; resets_at?: string }
type Batch = { revision_id?: string | null; phase_id?: string; status: string; quota_refunded?: boolean }
type Revision = { id: string; status: string; archived_at?: string | null; source_kind?: string; source_location?: string; created_at?: string }
type Project = { title: string; observer_revisions: Revision[] }

/** Earlier evaluations of this version in this phase that used a daily evaluation. */
export function countedEvaluations(batches: Batch[] | null | undefined, revisionId: string, phaseId: string): number {
  return (batches ?? []).filter(b => b.revision_id === revisionId && b.phase_id === phaseId && !b.quota_refunded).length
}

/** A version the team has not evaluated can be withdrawn, except while its preparation job runs. */
export function canWithdraw(revision: Revision, batches: Batch[] | null | undefined): boolean {
  return !revision.archived_at && ['queued', 'reviewable', 'failed', 'approved'].includes(revision.status)
    && !(batches ?? []).some(b => b.revision_id === revision.id)
}

/** Withdrawn versions are hidden unless asked for; a project without visible versions is hidden too. */
export function visibleProjects<P extends Project>(projects: P[] | null | undefined, showWithdrawn: boolean): P[] {
  return (projects ?? []).map(p => ({ ...p, observer_revisions: p.observer_revisions.filter(r => showWithdrawn || !r.archived_at) }))
    .filter(p => p.observer_revisions.length)
}

export function withdrawnCount(projects: Project[] | null | undefined): number {
  return (projects ?? []).reduce((n, p) => n + p.observer_revisions.filter(r => r.archived_at).length, 0)
}

const repository = (url: string) => url.trim().toLowerCase().replace(/\/+$/, '').replace(/\.git$/, '')

/** The same project (title and repository, or title for a ZIP) was submitted in the last few minutes. */
export function recentDuplicate(projects: Project[] | null | undefined, title: string, url: string | null, now = Date.now(), windowMs = 10 * 60_000): boolean {
  return (projects ?? []).some(p => p.title.trim() === title.trim() && p.observer_revisions.some(r =>
    !r.archived_at && r.created_at && now - Date.parse(r.created_at) < windowMs
    && (url === null ? r.source_kind === 'zip' : r.source_kind === 'repository' && repository(r.source_location ?? '') === repository(url))))
}

/** The team's final version in a public formal phase (observer_final_versions). */
export type FinalVersion = {
  phase_id: string; deadline: string | null; locked: boolean
  /** The version the hidden final evaluation will use: the team's choice, else its best evaluation's version. */
  revision_id: string | null; source: 'chosen' | 'best' | null
  chosen_revision_id: string | null; chosen_by: string | null; chosen_at: string | null
  best_batch_id: string | null; best_revision_id: string | null; best_score: number | null
}

/** The final version shown for the selected phase: its own entry, else the first one. */
export function finalVersionFor(finals: FinalVersion[] | null | undefined, phaseId: string): FinalVersion | null {
  return (finals ?? []).find(f => f.phase_id === phaseId) ?? (finals ?? [])[0] ?? null
}

/** How a version relates to the final version: explicitly chosen, the default (best evaluation), or neither. */
export function finalRole(final: FinalVersion | null, revisionId: string): 'chosen' | 'best' | null {
  return final && final.revision_id === revisionId ? final.source : null
}

/** A team can still change its choice: before the deadline, never for the version it already chose. */
export function canChooseFinal(final: FinalVersion | null, revisionId: string, now = Date.now()): boolean {
  if (!final || final.locked || (final.deadline && Date.parse(final.deadline) <= now)) return false
  return final.chosen_revision_id !== revisionId
}

export function canClearFinal(final: FinalVersion | null, now = Date.now()): boolean {
  return !!final && !final.locked && !(final.deadline && Date.parse(final.deadline) <= now) && final.chosen_revision_id != null
}
