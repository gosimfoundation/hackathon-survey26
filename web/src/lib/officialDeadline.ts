/**
 * The announced deadline of a phase, when it differs from `ends_at`. The online phase's `ends_at`
 * (when the database stops accepting work) is the end of the post-deadline submission window;
 * every deadline shown to contestants is the announced one.
 */
const OFFICIAL_DEADLINE: Record<string, string> = { online: '2026-10-07T15:59:59Z' }

type PhaseLike = { slug?: string | null; ends_at: string | null }

/** The deadline to display for a phase. */
export function displayEndsAt(p: PhaseLike | null | undefined): string | null {
  if (!p) return null
  return (p.slug && OFFICIAL_DEADLINE[p.slug]) || p.ends_at
}

/** True between the announced deadline and `ends_at` (post-deadline submission window). */
export function inPostDeadlineWindow(p: PhaseLike | null | undefined, now = Date.now()): boolean {
  const official = p?.slug ? OFFICIAL_DEADLINE[p.slug] : undefined
  return !!official && !!p?.ends_at && now >= Date.parse(official) && now < Date.parse(p.ends_at)
}
