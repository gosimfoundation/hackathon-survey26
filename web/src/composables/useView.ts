import { ref } from 'vue'

/**
 * Site view (2026-10-12 trial): 'competition' is the hackathon site exactly as before (default);
 * 'benchmark' presents AOH as a benchmark for autonomous survey operations, with the Survey26 competition
 * as its first large stress test. The choice is remembered per browser (localStorage and a cookie, both
 * best-effort) and can be set by link with ?view=benchmark or ?view=competition.
 */
export type SiteView = 'competition' | 'benchmark'
const KEY = 'aoh-site-view'

function readStored(): SiteView {
  try {
    const v = window.localStorage.getItem(KEY)
    if (v === 'benchmark' || v === 'competition') return v
  } catch { /* storage unavailable */ }
  try {
    const m = document.cookie.match(/(?:^|;\s*)aoh-site-view=(benchmark|competition)/)
    if (m) return m[1] as SiteView
  } catch { /* cookies unavailable */ }
  return 'competition'
}

export const siteView = ref<SiteView>(typeof window === 'undefined' ? 'competition' : readStored())

export function setSiteView(v: SiteView): void {
  siteView.value = v
  try { window.localStorage.setItem(KEY, v) } catch { /* ignore */ }
  try { document.cookie = `${KEY}=${v}; path=/; max-age=31536000; samesite=lax` } catch { /* ignore */ }
}

/** ?view=… on any link switches the view (returns the requested view, or null when absent/invalid). */
export function viewFromQuery(q: unknown): SiteView | null {
  return q === 'benchmark' || q === 'competition' ? q : null
}
