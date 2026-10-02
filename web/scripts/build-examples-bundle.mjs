// Assemble the single combined examples bundle published as a GitHub Release asset:
//   gosim-observer-examples.zip
//     python/ typescript/ rust/        -- the three example agent projects (../examples/<lang>/)
//     docs/                            -- participant guide zh+en, generated the same way as
//                                         web/scripts/build-examples.mjs's per-zip docs/
//     local-cards/L1-L4, runner/       -- public local scoring kit, source of truth committed
//                                         once at ../examples/_local/{cards,runner}
//     README.md                        -- ../examples/_local/BUNDLE_README.md
//
// This is intentionally separate from build-examples.mjs (which still produces the per-language
// public/examples/<lang>.zip used elsewhere): this script's output is uploaded by hand to a
// GitHub Release, not served from the site. Run it, then:
//   gh release upload <tag> dist/gosim-observer-examples.zip --clobber
// (scripts/build-examples-bundle.sh at the repo root wraps both steps.)
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { zipSync } from 'fflate'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const examplesRoot = resolve(root, '..', 'examples')
const localRoot = resolve(examplesRoot, '_local')
const outDir = resolve(root, 'dist-bundle')
const mtime = new Date('2026-10-02T00:00:00Z')
const ZIP_ROOT = 'gosim-observer-examples'

const EXCLUDED_DIRS = new Set([
  'node_modules', 'dist', 'target', '__pycache__', '.git', '.pytest_cache', '.idea', '.vscode',
  'run_output',
])
const EXCLUDED_FILES = new Set(['.DS_Store', 'Thumbs.db'])
const excludeFile = (name) => EXCLUDED_FILES.has(name) || name.endsWith('.pyc') || name.endsWith('.pyo') || name.endsWith('.zip')
  || name === '.env' || (name.startsWith('.env.') && !['.env.example', '.env.sample', '.env.template'].includes(name))

const LANGS = [
  { lang: 'python', dir: 'python' },
  { lang: 'typescript', dir: 'typescript' },
  { lang: 'rust', dir: 'rust' },
]

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

function addTree(entries, sourceDir, zipPrefix) {
  for (const rel of walk(sourceDir)) {
    entries[`${zipPrefix}/${rel}`] = [readFileSync(resolve(sourceDir, rel)), { mtime, level: 9 }]
  }
}

// Shared participant-guide docs, generated fresh -- same source as build-examples.mjs's
// per-zip docs/, but placed once at the bundle root instead of once per language.
function buildDocsEntries() {
  const contentDir = resolve(root, 'src', 'content')
  const mediaDir = resolve(root, 'public', 'media', 'docs', 'v4-guide')
  const entries = {}

  const rewriteImages = (raw) => raw.replaceAll('__BASE_URL__media/docs/v4-guide/', 'images/')
  for (const [lang, file] of [['zh', 'docs.zh.md'], ['en', 'docs.en.md']]) {
    const raw = readFileSync(resolve(contentDir, file), 'utf8')
    entries[`${ZIP_ROOT}/docs/participant-guide.${lang}.md`] = [Buffer.from(rewriteImages(raw), 'utf8'), { mtime, level: 9 }]
  }

  if (existsSync(mediaDir)) {
    for (const name of readdirSync(mediaDir).sort()) {
      entries[`${ZIP_ROOT}/docs/images/${name}`] = [readFileSync(resolve(mediaDir, name)), { mtime, level: 9 }]
    }
  }
  return entries
}

for (const required of [resolve(localRoot, 'cards'), resolve(localRoot, 'runner'), resolve(localRoot, 'BUNDLE_README.md')]) {
  if (!existsSync(required)) {
    console.error(`[build-examples-bundle] missing ${required}`)
    process.exit(1)
  }
}

const entries = {}
for (const { lang, dir } of LANGS) {
  const sourceDir = resolve(examplesRoot, dir)
  if (!existsSync(sourceDir)) {
    console.error(`[build-examples-bundle] examples/${dir} not found`)
    process.exit(1)
  }
  addTree(entries, sourceDir, `${ZIP_ROOT}/${lang}`)
}

for (const card of readdirSync(resolve(localRoot, 'cards')).sort()) {
  addTree(entries, resolve(localRoot, 'cards', card), `${ZIP_ROOT}/local-cards/${card}`)
}
addTree(entries, resolve(localRoot, 'runner'), `${ZIP_ROOT}/runner`)
entries[`${ZIP_ROOT}/README.md`] = [readFileSync(resolve(localRoot, 'BUNDLE_README.md')), { mtime, level: 9 }]
Object.assign(entries, buildDocsEntries())

const zip = zipSync(entries, { level: 9, mtime })
mkdirSync(outDir, { recursive: true })
const outPath = resolve(outDir, 'gosim-observer-examples.zip')
writeFileSync(outPath, zip)
console.log(`[build-examples-bundle] ${Object.keys(entries).length} files -> ${outPath} (${zip.length} bytes)`)
