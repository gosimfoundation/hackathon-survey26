// One-line installs of the survey26 command-line tool and its agent skill, shown on 参赛 and in the /cli guide.
// `base` is the site's absolute base URL, e.g. https://create.gosim.org/survey26/platform/.
export const SITE_BASE = 'https://create.gosim.org/survey26/platform/'
export const SKILL_PATH = 'skills/survey26/SKILL.md'

export const cliInstallCommand = (base = SITE_BASE) => `curl -fsSLO ${base}survey26.py && python3 survey26.py --help`
export const skillInstallCommand = (base = SITE_BASE) =>
  `mkdir -p ~/.claude/skills/survey26 && curl -fsSL ${base}${SKILL_PATH} -o ~/.claude/skills/survey26/SKILL.md`

/** The site's absolute base URL in the browser (production: SITE_BASE). */
export function siteBase(origin: string | undefined, basePath: string): string {
  if (!origin || origin === 'null') return SITE_BASE
  return new URL(basePath || '/', origin).href
}
