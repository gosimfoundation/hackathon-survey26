/** Open track rules and browser-side helpers (no Supabase import, so unit tests can load it). */

export const MAX_ZIP_BYTES = 2 * 1024 * 1024
export const DAILY_LIMIT = 10
export const PENDING_LIMIT = 2

export interface OpenProblem { id: string; title_zh: string; title_en: string; version: string; seed_indices: number[]; kit_url: string; sort: number }
export interface OpenSubmission { id: string; problems: string[]; status: string; uses_model: boolean; model_name: string; key_hint: string; note: string; created_at: string }
export interface OpenScore { submission_id: string; problem_id: string; seeds: number; seeds_done: number; mean_total: number | null }
export interface OpenBoardRow { problem_id: string; player: string; best_total: number; uses_model: boolean; submissions: number; achieved_at: string }
export interface ModelChoice { base: string; model: string; key: string }

/** First problem with the ZIP itself, or null when it may be submitted. */
export function zipProblem(bytes: Uint8Array): 'empty' | 'too_large' | 'not_zip' | null {
  if (bytes.length < 22) return 'empty'
  if (bytes.length > MAX_ZIP_BYTES) return 'too_large'
  if (bytes[0] !== 0x50 || bytes[1] !== 0x4b) return 'not_zip'
  return null
}

export function modelProblem(m: ModelChoice | null): 'base' | 'model' | 'key' | null {
  if (!m) return null
  if (!/^https:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?(\/[A-Za-z0-9._~/-]*)?$/.test(m.base) || m.base.length > 300) return 'base'
  if (!m.model || m.model.length > 128 || /[\u0000-\u001f]/.test(m.model)) return 'model'
  if (!m.key || m.key.length > 400) return 'key'
  return null
}

/** Last up to four printable characters, for recognition only (same rule as the database). */
export function keyHint(key: string): string {
  return key.replace(/[^!-~]/g, '').slice(-4)
}

export function toBase64(bytes: Uint8Array): string {
  let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}

/** The executor's public key as built into the site (lib/executorKey.json); `null` while unpublished. */
export function executorKeyFrom(raw: unknown): JsonWebKey | null {
  const jwk = raw as JsonWebKey | null
  return jwk && jwk.kty === 'RSA' && typeof jwk.n === 'string' && typeof jwk.e === 'string' ? jwk : null
}

/** RSA-OAEP(SHA-256) in the browser: the database only ever sees ciphertext. */
export async function encryptKey(jwk: JsonWebKey, key: string): Promise<string> {
  const pub = await crypto.subtle.importKey('jwk', jwk, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt'])
  const ct = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, pub, new TextEncoder().encode(key))
  return toBase64(new Uint8Array(ct))
}

/** Database error codes raised by open_submit, in plain words. */
export const errorText: Record<string, { en: string; zh: string }> = {
  sign_in_required: { en: 'Please sign in first.', zh: '请先登录。' },
  invalid_problems: { en: 'Choose at least one task.', zh: '请至少选一道题。' },
  invalid_zip: { en: 'The file must be a ZIP (at most 2 MB) with agent.py at its root.', zh: '请上传 ZIP 文件（不超过 2 MB），根目录要有 agent.py。' },
  invalid_model: { en: 'Model API: an https base URL, a model name and a key are needed.', zh: '模型接口需要 https 地址、模型名和密钥。' },
  daily_limit: { en: `At most ${DAILY_LIMIT} submissions per day.`, zh: `每天最多提交 ${DAILY_LIMIT} 次。` },
  too_many_pending: { en: `At most ${PENDING_LIMIT} submissions can wait or run at once.`, zh: `同时排队或运行的提交最多 ${PENDING_LIMIT} 个。` },
  model_unavailable: { en: 'Model submissions are not open yet.', zh: '带模型的提交暂未开放。' },
}

export function explain(err: unknown): { en: string; zh: string } {
  const msg = String((err as { message?: string })?.message ?? err)
  for (const [code, text] of Object.entries(errorText)) if (msg.includes(code)) return text
  return { en: 'Something went wrong: ' + msg, zh: '出错了：' + msg }
}
