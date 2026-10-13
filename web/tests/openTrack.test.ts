import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { encryptKey, executorKeyFrom, explain, keyHint, MAX_ZIP_BYTES, modelProblem, toBase64, zipProblem } from '../src/lib/openTrackRules.ts'
import { benchmarkNavItems } from '../src/lib/benchmarkNav.ts'
import { STATIC_ROUTES } from '../../scripts/site-routes.mjs'

test('only real ZIPs up to 2 MB are accepted', () => {
  const zip = new Uint8Array(100); zip[0] = 0x50; zip[1] = 0x4b
  assert.equal(zipProblem(zip), null)
  assert.equal(zipProblem(new Uint8Array(10)), 'empty')
  assert.equal(zipProblem(new Uint8Array(100)), 'not_zip')
  const big = new Uint8Array(MAX_ZIP_BYTES + 1); big[0] = 0x50; big[1] = 0x4b
  assert.equal(zipProblem(big), 'too_large')
})

test('model settings follow the database rules', () => {
  assert.equal(modelProblem(null), null)
  assert.equal(modelProblem({ base: 'https://api.example.com/v1', model: 'm', key: 'sk-1' }), null)
  assert.equal(modelProblem({ base: 'http://api.example.com/v1', model: 'm', key: 'sk-1' }), 'base')
  assert.equal(modelProblem({ base: 'https://api.example.com/v1', model: '', key: 'sk-1' }), 'model')
  assert.equal(modelProblem({ base: 'https://api.example.com/v1', model: 'm', key: '' }), 'key')
  assert.equal(keyHint('sk-abcdef1234'), '1234')
  assert.equal(keyHint('ab'), 'ab')
})

test('base64 matches Node for large inputs', () => {
  const b = new Uint8Array(200000).map((_, i) => i % 251)
  assert.equal(toBase64(b), Buffer.from(b).toString('base64'))
})

test('keys are encrypted with RSA-OAEP SHA-256 and decrypt with the private key', async () => {
  const pair = await crypto.subtle.generateKey({ name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['encrypt', 'decrypt'])
  const jwk = await crypto.subtle.exportKey('jwk', pair.publicKey)
  const ct = await encryptKey(jwk, 'sk-secret')
  const plain = await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, pair.privateKey, Buffer.from(ct, 'base64'))
  assert.equal(new TextDecoder().decode(plain), 'sk-secret')
})

test('database error codes become plain sentences', () => {
  assert.match(explain(new Error('daily_limit')).zh, /每天最多/)
  assert.match(explain({ message: 'P0001: too_many_pending' }).en, /at once/)
})

test('the open track has a static route, a page title in both languages and a benchmark-view link', () => {
  assert.equal((STATIC_ROUTES as Record<string, string>).open, 'open')
  for (const lang of ['en', 'zh']) {
    const meta = JSON.parse(readFileSync(new URL(`../src/i18n/${lang}.json`, import.meta.url), 'utf8')).meta.pages.open
    assert.ok(meta.title && meta.description, lang)
  }
  assert.ok(benchmarkNavItems.some(i => i.to === '/open'))
})

test('the executor key is pinned in the bundle (real RSA key since the 2026-10-13 launch) and junk keys stay off', () => {
  const pinned = JSON.parse(readFileSync(new URL('../src/lib/executorKey.json', import.meta.url), 'utf8'))
  assert.ok(executorKeyFrom(pinned))
  assert.equal(executorKeyFrom({ kty: 'EC', n: 'x', e: 'y' }), null)
  assert.ok(executorKeyFrom({ kty: 'RSA', n: 'abc', e: 'AQAB' }))
})
