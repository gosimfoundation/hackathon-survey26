import { computed, onMounted, onUnmounted, ref } from 'vue'
import { isSupabaseConfigured, supabase } from '../lib/supabase'
import { loadPhases, phaseStatus, type Phase } from '../lib/data'
import { startDay, startMoment, timeLeft, upcomingPublicPhases, type ScheduledPhase, type ScheduledPhaseRow } from '../lib/phaseSchedule'
import { useI18n } from './useI18n'

// One shared fetch for every clock on the page (header + hero); refreshed at most once a minute.
const shared = ref<Phase[]>([])
const upcoming = ref<ScheduledPhase[]>([])
const loaded = ref(false)
let inflight: Promise<void> | null = null
let fetchedAt = 0

/**
 * Later public stages of the event, whatever the current competition is (in practice mode the
 * current list only holds the Playground). Row-level security decides which phases are visible;
 * team-restricted test phases are also dropped by `upcomingPublicPhases`.
 */
async function loadUpcoming(): Promise<ScheduledPhase[]> {
  const { data, error } = await supabase.from('phases')
    .select('id,slug,name_en,name_zh,sort_order,starts_at,ends_at,is_active,observer_settings:observer_phase_settings(access_team_id,sealed)')
    .eq('is_active', true).gt('starts_at', new Date().toISOString())
    .order('starts_at', { ascending: true }).limit(10)
  if (error) throw error
  return upcomingPublicPhases((data ?? []) as ScheduledPhaseRow[], Date.now())
}

function fetchPhases(): Promise<void> {
  if (inflight) return inflight
  if (Date.now() - fetchedAt < 60_000 && loaded.value) return Promise.resolve()
  inflight = (async () => {
    // A slow backend must not hold the page in limbo. Show no invented date while
    // unavailable; a late successful answer still replaces the empty lists.
    const attempt: Promise<[Phase[], ScheduledPhase[]]> = isSupabaseConfigured
      ? Promise.all([loadPhases().catch(() => []), loadUpcoming().catch(() => [])])
      : Promise.resolve([[], []])
    const apply = ([current, later]: [Phase[], ScheduledPhase[]]) => { shared.value = current; upcoming.value = later }
    const result = await Promise.race([attempt, new Promise<null>(resolve => window.setTimeout(() => resolve(null), 4000))])
    if (result) apply(result)
    else void attempt.then(lists => { apply(lists); fetchedAt = Date.now() })
    loaded.value = true; fetchedAt = Date.now(); inflight = null
  })()
  return inflight
}

export interface CountdownParts { total: number; days: number; hours: number; minutes: number; seconds: number }
export function countdownParts(targetIso: string | null, now: number): CountdownParts {
  const total = Math.max(0, targetIso ? new Date(targetIso).getTime() - now : 0)
  const s = Math.floor(total / 1000)
  return { total, days: Math.floor(s / 86400), hours: Math.floor((s % 86400) / 3600), minutes: Math.floor((s % 3600) / 60), seconds: s % 60 }
}

export type NextPhase = Pick<Phase, 'id' | 'slug' | 'name_en' | 'name_zh' | 'sort_order' | 'starts_at' | 'ends_at'>

/**
 * The single current competition phase, the next public stage and a per-second countdown to its start.
 * Dates always come from the phase configuration.
 */
export function usePhaseClock() {
  const { t, tf, pick, locale } = useI18n()
  const now = ref(Date.now())
  let timer: number | undefined
  onMounted(() => { void fetchPhases(); timer = window.setInterval(() => { now.value = Date.now() }, 1000) })
  onUnmounted(() => { if (timer) window.clearInterval(timer) })

  const phases = computed(() => shared.value.filter(p => p.is_active).map(p => ({ ...p, status: phaseStatus(p, now.value) })))
  const current = computed<Phase | null>(() => phases.value.filter(p => p.status === 'open').sort((a, b) => a.sort_order - b.sort_order)[0] ?? null)
  const next = computed<NextPhase | null>(() => {
    const later: NextPhase[] = [
      ...phases.value.filter(p => p.status === 'upcoming' && p.starts_at),
      ...upcoming.value.filter(p => Date.parse(p.starts_at!) > now.value),
    ].filter((p, index, all) => p.id !== current.value?.id && all.findIndex(q => q.id === p.id) === index)
    return later.sort((a, b) => Date.parse(a.starts_at!) - Date.parse(b.starts_at!) || a.sort_order - b.sort_order)[0] ?? null
  })
  /** Kept for display consumers; an unavailable schedule never invents a stage. */
  const usingFallback = computed(() => false)
  const nextStartsAt = computed<string | null>(() => next.value?.starts_at ?? current.value?.ends_at ?? null)
  const countdown = computed(() => countdownParts(nextStartsAt.value, now.value))
  /** "10月5日开赛 · 还有 9 天" in the viewer's own time zone. */
  const nextStart = computed(() => {
    const at = next.value?.starts_at
    if (!next.value || !at) return null
    const left = timeLeft(at, now.value)
    return {
      name: pick(next.value.name_en, next.value.name_zh),
      day: tf('phase_clock.starts_on', { date: startDay(at, locale.value) }),
      moment: startMoment(at, locale.value),
      left: left.unit === 'soon' ? t('phase_clock.left_soon') : tf(`phase_clock.left_${left.unit}`, { n: left.n }),
    }
  })
  const nextLine = computed(() => nextStart.value ? tf('phase_clock.next_line', nextStart.value) : '')

  return { phases, loaded, current, next, nextStartsAt, nextStart, nextLine, usingFallback, countdown, now }
}
