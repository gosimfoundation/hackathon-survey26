import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

// The practice stage has one name only: 练习赛 / Practice. "Playground" must never reach participants.
const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIRS = ['src', 'public', 'index.html']

function* files(path: string): Generator<string> {
  let stat
  try { stat = statSync(path) } catch { return }
  if (stat.isDirectory()) for (const name of readdirSync(path)) yield* files(join(path, name))
  else if (/\.(vue|ts|json|md|html|txt|css)$/.test(path)) yield path
}

test('no participant-facing web text says Playground', () => {
  const hits: string[] = []
  for (const dir of DIRS) for (const file of files(join(ROOT, dir))) {
    readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
      if (/playground/i.test(line)) hits.push(`${file.slice(ROOT.length)}:${i + 1}`)
    })
  }
  assert.deepEqual(hits, [])
})
