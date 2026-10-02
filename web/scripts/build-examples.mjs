// Assemble the public example-project downloads for the Resources page:
//   public/examples/<lang>.zip  (../examples/<lang>/ under <zipRoot>/, plus a generated docs/)
//
// Each example in ../examples/ ships without a docs/ folder; the participant guide (zh + en,
// with its images) is generated here from web/src/content/docs.{zh,en}.md and
// web/public/media/docs/v4-guide/*, so the site's one copy of the guide is the only copy -- the
// zip's docs/ is never committed to the repo. Images are renamed to docs/images/ in the zip, and
// the __BASE_URL__media/docs/v4-guide/ image references in the zh guide are rewritten to match.
//
// A card only appears in EXAMPLES below (and thus only produces a zip) once its source folder
// exists under ../examples/ -- adding a new language later is one folder copy + one entry here.
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { zipSync } from 'fflate'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const examplesRoot = resolve(root, '..', 'examples')
const outDir = resolve(root, 'public', 'examples')
const mtime = new Date('2026-10-01T00:00:00Z')

const EXCLUDED_DIRS = new Set(['node_modules', 'dist', 'target', '__pycache__', '.git', '.pytest_cache', '.idea', '.vscode'])
const EXCLUDED_FILES = new Set(['.DS_Store', 'Thumbs.db'])
const excludeFile = (name) => EXCLUDED_FILES.has(name) || name.endsWith('.pyc') || name.endsWith('.pyo') || name.endsWith('.zip')
  || name === '.env' || (name.startsWith('.env.') && !['.env.example', '.env.sample', '.env.template'].includes(name))

// lang: public zip name (public/examples/<lang>.zip); dir: folder under ../examples/;
// zipRoot: top-level folder name inside the zip.
const EXAMPLES = [
  { lang: 'python', dir: 'python', zipRoot: 'python-agent' },
  { lang: 'typescript', dir: 'typescript', zipRoot: 'ts-agent' },
  { lang: 'rust', dir: 'rust', zipRoot: 'rust-agent' },
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

// Shared participant-guide docs, generated fresh for every zip -- not stored under examples/.
function buildDocsEntries(zipRoot) {
  const contentDir = resolve(root, 'src', 'content')
  const mediaDir = resolve(root, 'public', 'media', 'docs', 'v4-guide')
  const entries = {}

  const zhRaw = readFileSync(resolve(contentDir, 'docs.zh.md'), 'utf8')
  const zhRewritten = zhRaw.replaceAll('__BASE_URL__media/docs/v4-guide/', 'images/')
  entries[`${zipRoot}/docs/participant-guide.zh.md`] = [Buffer.from(zhRewritten, 'utf8'), { mtime, level: 9 }]

  const enRaw = readFileSync(resolve(contentDir, 'docs.en.md'), 'utf8')
  entries[`${zipRoot}/docs/participant-guide.en.md`] = [Buffer.from(enRaw, 'utf8'), { mtime, level: 9 }]

  if (existsSync(mediaDir)) {
    for (const name of readdirSync(mediaDir).sort()) {
      entries[`${zipRoot}/docs/images/${name}`] = [readFileSync(resolve(mediaDir, name)), { mtime, level: 9 }]
    }
  }
  return entries
}

mkdirSync(outDir, { recursive: true })

for (const { lang, dir, zipRoot } of EXAMPLES) {
  const sourceDir = resolve(examplesRoot, dir)
  if (!existsSync(sourceDir)) {
    console.log(`[build-examples] ${lang}: no examples/${dir}/ yet, skipping`)
    continue
  }
  for (const required of ['AGENTS.md', 'README.md']) {
    if (!existsSync(resolve(sourceDir, required))) {
      console.error(`[build-examples] examples/${dir} is incomplete: missing ${required}`)
      process.exit(1)
    }
  }

  const entries = {}
  for (const rel of walk(sourceDir)) {
    entries[`${zipRoot}/${rel}`] = [readFileSync(resolve(sourceDir, rel)), { mtime, level: 9 }]
  }
  const codeFileCount = Object.keys(entries).length
  Object.assign(entries, buildDocsEntries(zipRoot))

  const zip = zipSync(entries, { level: 9, mtime })
  const outPath = resolve(outDir, `${lang}.zip`)
  writeFileSync(outPath, zip)
  console.log(`[build-examples] ${lang}: ${codeFileCount} project files + docs -> public/examples/${lang}.zip (${zip.length} bytes)`)
}
