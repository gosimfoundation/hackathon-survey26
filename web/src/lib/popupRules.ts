// Popup rules (pure, unit-tested). Every site popup follows the same three rules:
//  1. Each person sees each popup at most once. A popup is identified by a content key, so it shows again only
//     when it is meant to (Kimi plan team + role, quota reset id, inbox row id).
//     Pinned announcements are the exception: they come back on every page load until the person has closed them
//     ANNOUNCEMENT_CLOSES times (key id + notify_version; an organizer's "remind everyone" bumps the version and
//     starts a fresh count, editing the text never re-shows it).
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

type AnnouncementRef = { id: string | number; notify_version?: number | null }
const annVersion = (a: AnnouncementRef) => Math.max(1, Math.floor(Number(a.notify_version) || 1))
const annId = (a: AnnouncementRef) => String(a.id).replace(/[^0-9A-Za-z-]/g, '')
/** Pinned announcements stop for good after this many closes (per id + notify_version). */
export const ANNOUNCEMENT_CLOSES = 2
/** Base key of an announcement's notify_version: "remind everyone" (notify_version + 1) starts a fresh count. */
export const announcementOffKey = (a: AnnouncementRef) => `ann-off:${annId(a)}:v${annVersion(a)}`
/** Recorded on the n-th close (1..ANNOUNCEMENT_CLOSES). Only these keys count; older snooze/off keys do not. */
export const announcementCloseKey = (a: AnnouncementRef, n: number) => `${announcementOffKey(a)}#close${n}`

/** How many times this person has closed this notify_version of the announcement (0..ANNOUNCEMENT_CLOSES). */
export function announcementCloses(a: AnnouncementRef, seen: Set<string>): number {
  let n = 0
  while (n < ANNOUNCEMENT_CLOSES && seen.has(announcementCloseKey(a, n + 1))) n++
  return n
}

/**
 * The pinned announcement this page load shows: among those closed fewer than ANNOUNCEMENT_CLOSES times, the one
 * closed least (newest first on a tie). Each close moves the next page load on to another one; none is starved.
 */
export function pickAnnouncement<T extends AnnouncementRef>(pinnedNewestFirst: T[], seen: Set<string>): T | null {
  let best: T | null = null, bestCloses = ANNOUNCEMENT_CLOSES
  for (const a of pinnedNewestFirst) {
    const closes = announcementCloses(a, seen)
    if (closes < bestCloses) { best = a; bestCloses = closes }
  }
  return best
}
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
