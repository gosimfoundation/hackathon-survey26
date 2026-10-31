/**
 * Frozen leaderboard snapshots (/leaderboard/<phase>?snapshot=<id>): each one is the exact output of the board RPCs
 * (observer_card_board for every card tab, observer_super_board, observer_super_board_old and the baseline rows) for
 * the public boards at one moment, as an anonymous visitor saw them. The data is a static file under
 * public/snapshots/, so a snapshot never changes.
 */
/** phases: the slugs of the boards the snapshot holds. */
export interface BoardSnapshotInfo { id: string; takenAt: string; phases: string[]; label: { en: string; zh: string } }

export const BOARD_SNAPSHOTS: BoardSnapshotInfo[] = [
  { id: '20261031-1800', takenAt: '2026-10-31T10:00:00Z', phases: ['practice-projects', 'online', 'after-party'],
    label: { en: 'Oct 31, 18:00 (Beijing time)', zh: '10 月 31 日 18:00（北京时间）' } },
]

/** One phase's frozen board payloads; card_board is keyed by card slug, '' for the overall tab. */
export interface SnapshotPhase {
  slug: string
  card_board: Record<string, unknown>
  super: unknown
  super_old: unknown
  baseline: unknown
  super_baseline: unknown
}
export interface BoardSnapshot { info: BoardSnapshotInfo; phases: Record<string, SnapshotPhase> }

const loaded = new Map<string, Promise<BoardSnapshot | null>>()

/** The snapshot with this id, or null when there is none (unknown id or the file could not be read). */
export function loadBoardSnapshot(id: string): Promise<BoardSnapshot | null> {
  const info = BOARD_SNAPSHOTS.find(s => s.id === id)
  if (!info) return Promise.resolve(null)
  if (!loaded.has(id)) {
    loaded.set(id, fetch(`${import.meta.env.BASE_URL}snapshots/board-${id}.json`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error(String(response.status))))
      .then(data => ({ info, phases: (data?.phases ?? {}) as Record<string, SnapshotPhase> }))
      .catch(() => { loaded.delete(id); return null }))
  }
  return loaded.get(id)!
}
