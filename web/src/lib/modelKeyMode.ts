/** How a team's model key reaches formal runs. */
export type ModelKeyMode = 'stored' | 'relay'

/**
 * Not saving the key (the page relay) is the default. Saving it encrypted on the
 * server is an explicit opt-in: only a team that chose it, or saved a key, is in
 * stored mode.
 */
export const DEFAULT_MODEL_KEY_MODE: ModelKeyMode = 'relay'

export function teamModelMode(teamModel: { mode?: string | null } | null | undefined): ModelKeyMode {
  return teamModel?.mode === 'stored' ? 'stored' : DEFAULT_MODEL_KEY_MODE
}

/**
 * The hidden final (organizers run each team's final version once after the
 * online phase freezes) has no team page open, so a team in relay mode cannot
 * make model calls there. Rule 2026-09-27: switch to stored mode before the
 * online phase ends. Warn while a final version applies and the team relays.
 */
export function relayMissesHiddenFinal(mode: ModelKeyMode, finalApplies: boolean): boolean {
  return finalApplies && mode === 'relay'
}
