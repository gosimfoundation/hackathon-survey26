/** `public.scenarios.name` carries a single, locale-agnostic value (see PR #194, which set the v4 practice
 * cards' name column to English text) — never show it to contestants directly. Practice cards and hackathon
 * task cards both follow a fixed slug naming scheme, so their display label is derived from the slug here
 * instead, with a proper translation per locale. Anything outside that scheme (legacy or future scenarios)
 * falls back to the DB name as before. */
const GREEK: Record<string, string> = { alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ' }

export function scenarioLabel(slug: string, name: string, locale: string): string {
  const practice = /^v4-practice-(alpha|beta|gamma|delta)$/.exec(slug)
  if (practice) {
    const symbol = GREEK[practice[1]!]
    return locale === 'zh' ? `练习卡 ${symbol}` : `Practice card ${symbol}`
  }
  const card = /^v4-([a-h])$/.exec(slug)
  if (card) {
    const letter = card[1]!.toUpperCase()
    return locale === 'zh' ? `任务卡 ${letter}` : `Card ${letter}`
  }
  return name
}
