// Assemble the public starter-kit downloads from ../archive/starter_kit_v3 (challenge v3).
//   public/downloads/agent-observer-starter-kit.zip  (whole kit under agent-observer-starter-kit/)
//   public/downloads/scoring_core.py, contracts.py, score_config.json  (public scorer + contracts + weights)
//   public/skill.md
// Excluded from the zip: __pycache__, .venv, run_output, demo_week_output, scratch, *.pyc, *.zip, any .env (except .env.example).
// {{BASE_URL}} / {{SUPABASE_URL}} / {{SUPABASE_ANON_KEY}} in README.md and SKILL.md are filled from the build environment.
import { readFileSync, writeFileSync, mkdirSync, existsSync, copyFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { dirname, resolve, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { zipSync } from 'fflate'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const kitDir = process.env.STARTER_KIT_DIR || resolve(root, '..', 'archive', 'starter_kit_v3')
const outDir = resolve(root, 'public', 'downloads')
const zipFolder = 'agent-observer-starter-kit'

const EXCLUDED_DIRS = new Set(['__pycache__', '.venv', 'venv', 'run_output', 'demo_week_output', 'scratch', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.git', '.idea', '.vscode'])
const EXCLUDED_FILES = new Set(['.DS_Store', 'Thumbs.db'])
const excludeFile = (name) => EXCLUDED_FILES.has(name) || name.endsWith('.pyc') || name.endsWith('.pyo') || name.endsWith('.zip')
  || (name === '.env') || (name.startsWith('.env.') && name !== '.env.example')

if (!existsSync(kitDir)) {
  console.warn(`[build-kit] starter kit not found at ${kitDir}; skipping download bundle.`)
  process.exit(0)
}
for (const required of ['README.md', 'SKILL.md', 'local_runner.py', 'agent/minimal_agent.py', 'challenge/scoring_core.py', 'scenarios/dev-reference/config/score_config.json',
                        'scenarios/demo-week/config/scenario_config.json', 'run_demo_week.sh']) {
  if (!existsSync(resolve(kitDir, required))) { console.error(`[build-kit] starter kit is incomplete: missing ${required}`); process.exit(1) }
}
mkdirSync(outDir, { recursive: true })

// Placeholders in SKILL.md / README.md are filled from the build environment so the downloaded kit is ready to use.
const subst = {
  '{{BASE_URL}}': (process.env.VITE_SITE_URL || '').replace(/\/+$/, '') || 'https://<site>',
  '{{SUPABASE_URL}}': process.env.VITE_SUPABASE_URL || 'https://<ref>.supabase.co',
  '{{SUPABASE_ANON_KEY}}': process.env.VITE_SUPABASE_ANON_KEY || '<anon key>',
}
const fill = (buf) => Buffer.from(Object.entries(subst).reduce((t, [k, v]) => t.split(k).join(v), buf.toString('utf8')))
const FILLED = new Set(['README.md', 'SKILL.md', 'fetch_scenario.py', 'sac_submit.py'])

function walk(dir, rel = '') {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const relPath = rel ? `${rel}/${entry.name}` : entry.name
    if (entry.isDirectory()) {
      if (!EXCLUDED_DIRS.has(entry.name)) out.push(...walk(resolve(dir, entry.name), relPath))
    } else if (entry.isFile() && !excludeFile(entry.name)) {
      out.push(relPath)
    }
  }
  return out
}

const entries = {}
const mtime = new Date('2026-09-10T00:00:00Z')
let rawBytes = 0
for (const rel of walk(kitDir)) {
  const raw = readFileSync(resolve(kitDir, rel))
  rawBytes += raw.length
  // executable bit for the double-click launchers so `unzip` on macOS / Linux restores it (UNIX external attrs)
  const executable = /\.(command|sh)$/.test(rel)
  entries[`${zipFolder}/${rel}`] = [FILLED.has(rel) ? fill(raw) : raw, executable ? { mtime, level: 9, os: 3, attrs: 0o100755 << 16 } : { mtime, level: 9 }]
}
const zip = zipSync(entries, { level: 9, mtime })
writeFileSync(resolve(outDir, 'agent-observer-starter-kit.zip'), zip)

// Public scorer, contracts and score weights as standalone downloads (linked from the resources page).
copyFileSync(resolve(kitDir, 'challenge', 'scoring_core.py'), resolve(outDir, 'scoring_core.py'))
copyFileSync(resolve(kitDir, 'challenge', 'contracts.py'), resolve(outDir, 'contracts.py'))
copyFileSync(resolve(kitDir, 'scenarios', 'dev-reference', 'config', 'score_config.json'), resolve(outDir, 'score_config.json'))
for (const stale of ['scorer.py', 'protocol.py']) {
  const p = resolve(outDir, stale)
  if (existsSync(p)) { rmSync(p); console.log(`[build-kit] removed stale ${relative(root, p)}`) }
}
writeFileSync(resolve(root, 'public', 'skill.md'), fill(readFileSync(resolve(kitDir, 'SKILL.md'))))

const count = Object.keys(entries).length
console.log(`[build-kit] wrote ${count} files (${rawBytes} bytes raw) into ${relative(root, resolve(outDir, 'agent-observer-starter-kit.zip'))} (${zip.length} bytes)`)
for (const name of ['scoring_core.py', 'contracts.py', 'score_config.json']) console.log(`[build-kit] public/downloads/${name}: ${statSync(resolve(outDir, name)).size} bytes`)
console.log(`[build-kit] public/skill.md: ${statSync(resolve(root, 'public', 'skill.md')).size} bytes`)
void sep

// Language-neutral online local runner; no scenarios, credentials or caches.
const onlineEntries = {}
for (const pkg of ['project_platform', 'challenge']) {
  const source = resolve(root, '..', pkg)
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    if (entry.isFile() && entry.name.endsWith('.py')) {
      onlineEntries[`observer-local-runner/${pkg}/${entry.name}`] = [readFileSync(resolve(source, entry.name)), { mtime, level: 9 }]
    }
  }
}
onlineEntries['observer-local-runner/README.md'] = [readFileSync(resolve(root, '..', 'docs/local-project-runner.md')), { mtime, level: 9 }]
writeFileSync(resolve(outDir, 'observer-local-runner.zip'), zipSync(onlineEntries, { level: 9, mtime }))
console.log(`[build-kit] online runner: ${Object.keys(onlineEntries).length} trusted files; no scenario data`)
