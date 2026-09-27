// Locale-aware wording for the complete-project workflow and the evaluation records.
export type TextLocale = 'en' | 'zh' | 'ja' | 'fr'

const TAGS: Record<TextLocale, string> = { zh: 'zh-CN', en: 'en-US', ja: 'ja-JP', fr: 'fr-FR' }

/** A timestamp in the viewer's time zone, spelled for the page language ("2026/09/26 19:00" on zh). */
export function formatDateTime(value: string | null | undefined, locale: TextLocale, timeZone?: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(TAGS[locale] ?? 'en-US', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    ...(timeZone ? { timeZone } : {}),
  }).format(date)
}

const clock = (hours: number, minutes: number) => `${hours}:${String(minutes).padStart(2, '0')}`

/** The daily evaluation reset with an explicit time zone, e.g. "每天 UTC 0:00（北京时间 8:00）重置". */
export function formatDailyReset(resetsAt: string | null | undefined, locale: TextLocale): string {
  const date = resetsAt ? new Date(resetsAt) : null
  const valid = date && !Number.isNaN(date.getTime())
  const hours = valid ? date.getUTCHours() : 0, minutes = valid ? date.getUTCMinutes() : 0
  const beijing = clock((hours + 8) % 24, minutes)
  return locale === 'zh'
    ? `每天 UTC ${clock(hours, minutes)}（北京时间 ${beijing}）重置`
    : `Resets daily at ${clock(hours, minutes)} UTC (${beijing} Beijing time)`
}

// Fixed revision errors written by the database; project-specific reasons stay as they are.
const REVISION_ERRORS: Record<string, string> = {
  'Project preparation failed. Please retry.': '项目准备失败，请重新提交。',
  'Project preparation did not finish. Please retry.': '项目准备未能完成，请重新提交。',
  'Project scheduling failed. Please retry.': '项目排队失败，请重新提交。',
  'Invalid preparation result. Please retry.': '项目准备结果无效，请重新提交。',
  'Public test scenario is unavailable.': '公开测试场景暂不可用，请稍后重新提交。',
  'Public test failed. Check the project interface and submit again.': '公开场景测试未通过，请检查项目接口后重新上传。',
}
const PREPARATION_FAILED = 'Project preparation failed: '

/** Revision errors are stored in English; show them in Chinese on the zh page. */
export function revisionErrorText(error: string | null | undefined, locale: TextLocale): string {
  const text = (error ?? '').trim()
  if (!text || locale !== 'zh') return text
  if (REVISION_ERRORS[text]) return REVISION_ERRORS[text]
  if (text.startsWith(PREPARATION_FAILED)) return `项目准备失败：${text.slice(PREPARATION_FAILED.length)}`
  return text
}

/** A failed repository revision can be prepared again from the same URL; a ZIP must be uploaded again. */
export function canPrepareAgain(revision: { status: string; source_kind?: string; source_location?: string; archived_at?: string | null }): boolean {
  return revision.status === 'failed' && !revision.archived_at && revision.source_kind === 'repository' &&
    /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/.test(revision.source_location ?? '')
}
