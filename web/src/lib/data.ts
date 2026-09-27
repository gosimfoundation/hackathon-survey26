import { supabase } from './supabase'
import { normalizeKimiPlanStatus, type KimiPlanStatus } from './kimiPlan'

export type PhaseStatus = 'open' | 'upcoming' | 'closed' | 'disabled'
export type LeaderboardMode = 'live' | 'frozen' | 'hidden' | 'published'

export interface Scenario {
  id: string; slug: string; name: string; description: string | null
  weather_public: boolean; tiles_public: boolean; forecasts_public: boolean; events_public: boolean; is_active: boolean
  n_slots: number | null; n_nights: number | null; n_tiles: number | null; n_targets: number | null; n_requests: number | null
  global_wallclock_seconds: number | null; contract: string | null; created_at: string
  /** Withheld from participants: `seed`, `checksum` and `manifest` would let anyone rebuild a hidden-weather
   *  scenario locally, so anon/authenticated have no column privilege on them. Only `admin_scenarios()` fills
   *  these in — everywhere else they are undefined. */
  seed?: number | null; checksum?: string | null; manifest?: Record<string, unknown> | null
}

/** The scenario columns participants are allowed to read (see migration 20260915000100_hide_scenario_seeds). */
export const SCENARIO_PUBLIC_COLUMNS =
  'id, slug, name, description, weather_public, forecasts_public, events_public, tiles_public, is_active, ' +
  'n_slots, n_nights, n_tiles, n_targets, n_requests, global_wallclock_seconds, contract, created_at'

/** Files of a scenario directory in the `scenarios` bucket (`<slug>/config/<file>` and `<slug>/outputs/reference/<file>`). */
export type ScenarioFileGroup = 'config' | 'data' | 'weather' | 'forecasts' | 'events'
export interface ScenarioFile { key: string; name: string; group: ScenarioFileGroup; flag?: 'weather_public' | 'forecasts_public' | 'events_public' }
export const SCENARIO_FILES: ScenarioFile[] = [
  ...['scenario_config.json', 'calendar_config.json', 'tile_config.json', 'weather_config.json', 'request_config.json', 'workflow_config.json', 'score_config.json']
    .map(name => ({ key: `config/${name}`, name, group: 'config' as const })),
  ...['night_calendar.csv', 'slots.csv', 'tiles.csv', 'targets.csv', 'tile_windows.csv', 'observation_requests.csv', 'observation_request_tiles.csv',
    'scenario_manifest.json', 'calendar_metadata.json', 'catalog_metadata.json', 'observation_request_metadata.json']
    .map(name => ({ key: `outputs/reference/${name}`, name, group: 'data' as const })),
  { key: 'outputs/reference/weather.csv', name: 'weather.csv', group: 'weather', flag: 'weather_public' },
  { key: 'outputs/reference/weather_metadata.json', name: 'weather_metadata.json', group: 'weather', flag: 'weather_public' },
  { key: 'outputs/reference/weather_forecasts.csv', name: 'weather_forecasts.csv', group: 'forecasts', flag: 'forecasts_public' },
  { key: 'outputs/reference/weather_events.csv', name: 'weather_events.csv', group: 'events', flag: 'events_public' },
]
export const scenarioFileVisible = (s: Scenario, f: ScenarioFile) => !f.flag || Boolean(s[f.flag])
export const scenarioObjectKey = (slug: string, file: string) => `${slug}/${file}`
export interface Phase {
  id: string; slug: string; name_en: string; name_zh: string; description_en: string | null; description_zh: string | null
  sort_order: number; starts_at: string | null; ends_at: string | null; allow_results: boolean; allow_agents: boolean
  daily_limit: number; leaderboard_mode: LeaderboardMode; counts_for_final: boolean; is_active: boolean
  scenarios: Scenario[]; status: PhaseStatus
  observer_settings?: { projects_enabled: boolean; local_sessions_enabled: boolean; daily_batches: number; sealed?: boolean } | null
}
export interface Announcement {
  id: string; title_en: string; title_zh: string; body_en: string | null; body_zh: string | null
  level: 'info' | 'warning' | 'success'; is_pinned: boolean; is_published: boolean; created_at: string
}
export interface LeaderboardEntry {
  rank: number; team_id: string; team_name: string; team_slug: string; total_score: number; science_score: number
  completion_rate: number; uniformity_score: number
  base_science: number; program_bonus: number; request_reward: number; coverage_bonus: number | null; coverage_evenness: number | null; penalty_total: number; completed_tiles: number | null; required_missing: number | null
  submission_count: number; best_submission_id: number | null; kind: string | null; scored_at: string | null; leader_github: string | null
  /** The scenario this board ranks; null on the final board, which averages every scenario of the phase. */
  scenario_slug: string | null
  observer_batch_id?: string | null; report_reward?: number
  calibrated?: boolean; raw_total_score?: number | null
}

export interface PhaseCopy {
  /** Human-facing summary without operational numbers baked in. */
  description: string
  /** Operational facts rendered separately from the description. */
  facts: string[]
}

/**
 * Keep user-facing phase copy consistent with the database row.
 *
 * The description fields are prose only; submission limits, result/package support,
 * and leaderboard visibility are derived from structured columns so future changes
 * only need to happen in one place.
 */
export function phaseCopy(
  phase: Pick<Phase, 'description_en' | 'description_zh' | 'allow_results' | 'allow_agents' | 'daily_limit' | 'leaderboard_mode' | 'observer_settings'>,
  locale: string,
): PhaseCopy {
  const description = (locale === 'zh' ? phase.description_zh : phase.description_en)
    ?? (locale === 'zh' ? phase.description_en : phase.description_zh)
    ?? ''
  const online=phase.observer_settings
  if (online?.projects_enabled || online?.local_sessions_enabled) return {description,facts:locale==='zh'
    ? [...(online.projects_enabled?['完整项目云端评测']:[]),...(online.local_sessions_enabled?['本地运行并提交 CSV']:[]),`每队每天 ${online.daily_batches} 次`,'同一次评测的多个场景取平均']
    : [...(online.projects_enabled?['Complete project cloud evaluation']:[]),...(online.local_sessions_enabled?['Local run with CSV submission']:[]),`${online.daily_batches} evaluations per team per day`,'Average across all scenarios in one evaluation']}
  const facts = locale === 'zh'
    ? [
        `结果文件 ${phase.allow_results ? '允许' : '不允许'}`,
        ...(phase.allow_agents ? ['智能体程序包 允许'] : []),
        `每队每天 ${phase.daily_limit} 次`,
        `榜单 ${phase.leaderboard_mode}`,
      ]
    : [
        `results files ${phase.allow_results ? 'allowed' : 'not allowed'}`,
        ...(phase.allow_agents ? ['agent packages allowed'] : []),
        `${phase.daily_limit} submissions per team per day`,
        `leaderboard ${phase.leaderboard_mode}`,
      ]
  return { description, facts }
}

export function phaseStatus(p: { is_active: boolean; starts_at: string | null; ends_at: string | null }, now = Date.now()): PhaseStatus {
  if (!p.is_active) return 'disabled'
  if (p.starts_at && now < new Date(p.starts_at).getTime()) return 'upcoming'
  if (p.ends_at && now > new Date(p.ends_at).getTime()) return 'closed'
  return 'open'
}

export async function loadPhases(all = false): Promise<Phase[]> {
  const { data, error } = await supabase
    .from('phases')
    .select(`*, observer_settings:observer_phase_settings(projects_enabled,local_sessions_enabled,daily_batches,sealed), phase_scenarios(scenario_id, scenarios(${SCENARIO_PUBLIC_COLUMNS}))`)
    .order('sort_order', { ascending: true })
  if (error) throw error
  const rows = ((data ?? []) as any[]).map(row => {
    const { phase_scenarios, ...rest } = row
    const scenarios = ((phase_scenarios ?? []) as any[]).map(link => link.scenarios).filter(Boolean) as Scenario[]
    scenarios.sort((a, b) => a.slug.localeCompare(b.slug))
    return { ...rest, scenarios, status: phaseStatus(rest) } as Phase
  })
  if (all) return rows
  const { loadCompetition } = await import('../stores/competition')
  const current = await loadCompetition()
  return rows.filter(p => p.id===current.projectPhaseId || isFinalBoard(p) || (current.phaseId ? p.id===current.phaseId : p.slug===(current.mode==='practice'?'practice':'online')))
}

/** The hidden final phase: readable only once organizers publish its results (the database hides it before). */
export function isFinalBoard(p: Pick<Phase, 'observer_settings'>): boolean {
  return !!p.observer_settings?.sealed
}

/** The online board on the fixed formal scenarios: live, but it does not decide the final ranking. */
export function isPublicFormalBoard(p: Pick<Phase, 'slug' | 'observer_settings'>): boolean {
  return p.slug === 'online' && !isFinalBoard(p)
}

/** The "main" phase: the counts_for_final one that is open/closed, else the first open one, else the first. */
export function mainPhase(phases: Phase[]): Phase | null {
  return phases.find(p => p.counts_for_final && (p.status === 'open' || p.status === 'closed'))
    ?? phases.find(p => p.status === 'open')
    ?? phases[0] ?? null
}

export async function loadScenarios(): Promise<Scenario[]> {
  const { data, error } = await supabase.from('scenarios').select(SCENARIO_PUBLIC_COLUMNS).order('slug')
  if (error) throw error
  return (data ?? []) as unknown as Scenario[]
}

/** Admin-only view of the same rows, including the withheld seed/checksum/manifest. */
export async function loadScenariosAsAdmin(): Promise<Scenario[]> {
  const { data, error } = await supabase.rpc('admin_scenarios')
  if (error) throw error
  return (data ?? []) as Scenario[]
}

export async function loadAnnouncements(limit?: number): Promise<Announcement[]> {
  let query = supabase.from('announcements').select('*').eq('is_published', true)
    .order('is_pinned', { ascending: false }).order('created_at', { ascending: false })
  if (limit) query = query.limit(limit)
  const { data, error } = await query
  if (error) throw error
  return (data ?? []) as Announcement[]
}

export interface PublicSettings { registrationOpen: boolean; registrationDeadline: string | null; mechanicsPublic: boolean }

export async function loadPublicSettings(): Promise<PublicSettings> {
  const fallback: PublicSettings = { registrationOpen: true, registrationDeadline: null, mechanicsPublic: false }
  try {
    const { data, error } = await supabase.from('site_settings').select('key, value')
      .in('key', ['registration_open', 'registration_deadline', 'mechanics_public'])
    if (error || !data) return fallback
    const map = Object.fromEntries((data as { key: string; value: unknown }[]).map(row => [row.key, row.value]))
    const openFlag = !(map.registration_open === false || map.registration_open === 'false')
    const deadline = typeof map.registration_deadline === 'string' ? map.registration_deadline : null
    const beforeDeadline = !deadline || Date.now() < Date.parse(deadline)
    return {
      registrationOpen: openFlag && beforeDeadline,
      registrationDeadline: deadline,
      mechanicsPublic: !(map.mechanics_public === false || map.mechanics_public === 'false'),
    }
  } catch { return fallback }
}

export async function loadRegistrationOpen(): Promise<boolean> {
  return (await loadPublicSettings()).registrationOpen
}

/**
 * Scenarios a phase's board can be switched between. Results files cover one scenario each, so a practice
 * board ranks one scenario at a time (longest first, the database's default); the final board averages
 * every scenario and has no switch.
 */
export function boardScenarios(phase: Pick<Phase, 'counts_for_final' | 'scenarios' | 'observer_settings'> | null): Scenario[] {
  if (!phase || phase.observer_settings?.projects_enabled || phase.observer_settings?.local_sessions_enabled || phase.counts_for_final || phase.scenarios.length < 2) return []
  return [...phase.scenarios].sort((a, b) => (b.n_nights ?? 0) - (a.n_nights ?? 0) || a.slug.localeCompare(b.slug))
}

export async function loadLeaderboard(phaseSlug: string | null, limit = 500, scenarioSlug: string | null = null, observerPhaseId?: string): Promise<LeaderboardEntry[]> {
  const { data, error } = observerPhaseId
    ? await supabase.rpc('observer_board', { p_phase: observerPhaseId, p_limit: limit })
    : await supabase.rpc('leaderboard', { p_phase_slug: phaseSlug, p_limit: limit, p_scenario_slug: scenarioSlug })
  if (error) throw error
  return ((data ?? []) as any[]).map((row, index) => ({
    rank: Number(row.rank ?? index + 1),
    leader_github: row.leader_github ? String(row.leader_github) : null,
    team_id: String(row.team_id),
    team_name: String(row.team_name ?? '—'),
    team_slug: String(row.team_slug ?? ''),
    total_score: Number(row.total_score ?? 0),
    science_score: Number(row.science_score ?? 0),
    completion_rate: Number(row.completion_rate ?? 0),
    uniformity_score: Number(row.uniformity_score ?? 0),
    base_science: Number(row.base_science ?? 0),
    program_bonus: Number(row.program_bonus ?? 0),
    request_reward: Number(row.request_reward ?? 0),
    coverage_bonus: row.coverage_bonus == null ? null : Number(row.coverage_bonus),
    coverage_evenness: row.coverage_evenness == null ? null : Number(row.coverage_evenness),
    penalty_total: Number(row.penalty_total ?? 0),
    completed_tiles: row.completed_tiles == null ? null : Number(row.completed_tiles),
    required_missing: row.required_missing == null ? null : Number(row.required_missing),
    submission_count: Number(row.submission_count ?? 0),
    best_submission_id: row.best_submission_id == null ? null : Number(row.best_submission_id),
    kind: row.kind ?? null,
    scored_at: row.scored_at ?? null,
    scenario_slug: row.scenario_slug ? String(row.scenario_slug) : null,
    observer_batch_id: row.observer_batch_id ?? null,
    calibrated: row.calibrated === true,
    raw_total_score: row.raw_total_score == null ? null : Number(row.raw_total_score),
    report_reward: Number(row.report_reward ?? 0),
  }))
}

export const SUBMISSION_SELECT = '*, phases(slug,name_en,name_zh), scenarios(slug,name), evaluations(*, scenarios(slug,name,tiles_public,weather_public,global_wallclock_seconds,n_tiles,n_nights))'
export const PENDING_STATUSES = new Set(['queued', 'running'])

// --- sponsor API credits (redeem codes) -----------------------------------
export interface RedeemProvider { provider: string; available: number; claimed_by_my_team: boolean }
export interface RedeemCode { provider: string; code: string; note: string; assigned_at: string | null }
export interface CreditsNote { en: string; zh: string }

export async function loadRedeemProviders(): Promise<RedeemProvider[]> {
  const { data, error } = await supabase.rpc('redeem_providers')
  if (error) throw error
  return ((data ?? []) as any[]).map(row => ({ provider: String(row.provider), available: Number(row.available ?? 0), claimed_by_my_team: Boolean(row.claimed_by_my_team) }))
}

export async function loadMyRedeemCodes(): Promise<RedeemCode[]> {
  const { data, error } = await supabase.rpc('my_redeem_codes')
  if (error) throw error
  return ((data ?? []) as any[]).map(row => ({ provider: String(row.provider), code: String(row.code), note: String(row.note ?? ''), assigned_at: row.assigned_at ?? null }))
}

/** Optional explanatory text above the credits panel (site_settings.credits_note = {en, zh}); empty strings when unset. */
export async function loadCreditsNote(): Promise<CreditsNote> {
  try {
    const { data, error } = await supabase.from('site_settings').select('value').eq('key', 'credits_note').maybeSingle()
    if (error || !data) return { en: '', zh: '' }
    const value = ((data as { value: unknown }).value ?? {}) as Record<string, unknown>
    return { en: typeof value.en === 'string' ? value.en : '', zh: typeof value.zh === 'string' ? value.zh : '' }
  } catch { return { en: '', zh: '' } }
}

// --- Kimi Coding Plan (captain claims one code once the team has a practice score) ---
export async function loadKimiPlanStatus(): Promise<KimiPlanStatus> {
  const { data, error } = await supabase.rpc('kimi_plan_status')
  if (error) throw error
  return normalizeKimiPlanStatus(data)
}

// --- participants wall -------------------------------------------------------

export interface WallEntry {
  id: string; name: string; role: string | null; affiliation: string | null; city: string | null; blurb: string | null
  astro_level: number; ai_level: number; looking_for_team: boolean; team_name: string | null; joined_at: string
  github: string | null; seeking: string; seeking_count: number
}
export interface ParticipantsStats { total: number; on_wall: number; looking: number; teams: number }

export async function loadParticipantsWall(limit = 60): Promise<WallEntry[]> {
  const { data, error } = await supabase.rpc('participants_wall', { p_limit: limit })
  if (error) throw error
  return (data ?? []) as WallEntry[]
}

export async function loadParticipantsStats(): Promise<ParticipantsStats> {
  const { data, error } = await supabase.rpc('participants_stats')
  if (error) throw error
  return data as ParticipantsStats
}

export async function revealTeammateContact(id: string): Promise<{ contact: string; github: string } | null> {
  const { data, error } = await supabase.rpc('teammate_contact', { p_id: id })
  if (error) throw error
  return (data ?? null) as { contact: string; github: string } | null
}
