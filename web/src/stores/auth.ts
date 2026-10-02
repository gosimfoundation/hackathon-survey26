import { reactive, computed } from 'vue'
import type { Session } from '@supabase/supabase-js'
import { supabase, isSupabaseConfigured } from '../lib/supabase'
import { loadCompetition } from './competition'

export interface MeTeam {
  id: string; name: string; slug: string; leader_id: string; invite_code: string
  project_idea: string | null; github_repo: string | null; max_size: number; is_locked: boolean; member_count: number
}
export interface Me {
  id: string; email: string; name: string; nickname: string; github: string | null; affiliation: string | null; role: string | null
  looking_for_team: boolean; locale: string | null; is_admin: boolean; is_banned: boolean; team: MeTeam | null
  astro_level: number; ai_level: number; city: string | null; contact: string | null
  heard_from: string | null; blurb: string | null; show_on_wall: boolean; seeking: string; seeking_count: number
  avatar_url: string
}

const state = reactive({
  session: null as Session | null,
  me: null as Me | null,
  ready: false,
  recovery: false,
})

let readyPromise: Promise<void> | null = null

export async function refreshMe(): Promise<Me | null> {
  if (!state.session) { state.me = null; return null }
  try {
    const { data, error } = await supabase.rpc('me')
    if (!error) state.me = (data as Me | null) ?? null
  } catch { /* keep the previous snapshot */ }
  return state.me
}

export function initAuth(): Promise<void> {
  if (readyPromise) return readyPromise
  readyPromise = (async () => {
    if (typeof window !== 'undefined' && /type=recovery/.test(window.location.hash)) state.recovery = true
    try {
      if (isSupabaseConfigured) {
        const { data } = await supabase.auth.getSession()
        state.session = data.session
        if (data.session) await refreshMe()
      }
    } catch { /* offline or misconfigured: treat as logged out */ }
    finally { state.ready = true }
    supabase.auth.onAuthStateChange((event, session) => {
      // Only a session gain or loss changes the beta entry; token refreshes must
      // not force competition refetches.
      const hadSession = Boolean(state.session)
      state.session = session
      if (event === 'PASSWORD_RECOVERY') state.recovery = true
      if (!session) { state.me = null; if (hadSession) window.setTimeout(() => { void loadCompetition(true) }, 0); return }
      // Do not await Supabase calls inside the callback (documented deadlock hazard).
      window.setTimeout(() => { void refreshMe(); if (!hadSession) void loadCompetition(true) }, 0)
    })
  })()
  return readyPromise
}

export async function signOut() {
  try { await supabase.auth.signOut() } catch { /* ignore */ }
  state.session = null
  state.me = null
}

export function useAuth() {
  return {
    state,
    isLoggedIn: computed(() => Boolean(state.session)),
    isAdmin: computed(() => Boolean(state.me?.is_admin)),
    me: computed(() => state.me),
    team: computed(() => state.me?.team ?? null),
    refreshMe,
    signOut,
    whenReady: () => initAuth(),
  }
}
