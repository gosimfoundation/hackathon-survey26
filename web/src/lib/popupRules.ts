// Popup rules (pure, unit-tested). Every site popup follows the same three rules:
//  1. Each person sees each popup at most once. A popup is identified by a content key, so it shows again only
//     when its content changes (announcement id + hash of its text, Kimi plan team + role, quota reset id, inbox row id).
//  2. Showing it counts as seen: closing it in any way (button, Esc, outside click, navigating away) or keeping it
//     on screen for SEEN_AFTER_MS marks it seen, so a reload never brings it back.
//  3. At most one popup per page load: the candidates that ask within SETTLE_MS are compared and the most important
//     one shows; the rest wait for a later visit.
// "Seen" lives in localStorage and, for signed-in users, on the server (my_seen_popups / mark_popups_seen).

export const POPUP_SEEN_KEY = 'sac.popups.seen'
export const SEEN_AFTER_MS = 3000
export const SETTLE_MS = 1500
const KEEP = 300

/** Lower is more important. Unknown names come last. */
export const POPUP_PRIORITY: Record<string, number> = {
  'browser-notice': 0,
  'team-requests': 1,
  'quota-reset': 2,
  'pinned-announcement': 3,
  'kimi-plan': 4,
  'compete-guide': 5,
}

/** The one popup this page load shows, among the names that asked (in asking order). */
export function pickPopup(candidates: string[]): string | null {
  let best: string | null = null
  for (const name of candidates) {
    if (best === null || (POPUP_PRIORITY[name] ?? 99) < (POPUP_PRIORITY[best] ?? 99)) best = name
  }
  return best
}

/** FNV-1a (32-bit), hex: a short stable fingerprint of a popup's text. */
export function contentHash(...parts: Array<string | null | undefined>): string {
  let h = 0x811c9dc5
  const text = parts.map(p => p ?? '').join('\u0000')
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

type AnnouncementText = { id: string | number; title_en?: string | null; title_zh?: string | null; body_en?: string | null; body_zh?: string | null }
export const announcementKey = (a: AnnouncementText) =>
  `ann:${a.id}:${contentHash(a.title_en, a.title_zh, a.body_en, a.body_zh)}`
export const kimiPlanKey = (teamId: string, role: string) => `kimi:${teamId}:${role}`
export const quotaResetKey = (id: string) => `quota:${id}`
export const inboxKey = (rowId: string) => `inbox:${rowId}`
export const BROWSER_NOTICE_KEY = 'browser-notice:safari:v1'

export function parseSeenList(raw: string | null): string[] {
  try {
    const value = JSON.parse(raw ?? '[]')
    return Array.isArray(value) ? value.map(String).filter(Boolean) : []
  } catch { return [] }
}

/** The stored list after adding `keys`: most recent last, capped, no duplicates. */
export function rememberSeenList(list: string[], keys: string[]): string[] {
  const add = new Set(keys)
  return list.filter(k => !add.has(k)).concat([...add]).slice(-KEEP)
}
