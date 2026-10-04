import assert from 'node:assert/strict'
import test from 'node:test'
import { configuredServices, newVariableCount, normalizePrefix, presetById, serviceNames, serviceWrites } from '../src/lib/modelServices.ts'

const v = (name: string, value: string | null, secret = false, hint = '') => ({ name, value, secret, hint })

test('default trio follows the protocol; a prefix makes its own trio', () => {
  assert.deepEqual(serviceNames('openai'), { key: 'OPENAI_API_KEY', baseUrl: 'OPENAI_BASE_URL', model: 'OPENAI_MODEL' })
  assert.deepEqual(serviceNames('anthropic'), { key: 'ANTHROPIC_API_KEY', baseUrl: 'ANTHROPIC_BASE_URL', model: 'ANTHROPIC_MODEL' })
  assert.equal(serviceNames('openai', ' kimi-2 ').key, 'KIMI_2_API_KEY')
  assert.equal(normalizePrefix('9 deep seek_'), 'DEEP_SEEK')
  assert.equal(normalizePrefix('  '), '')
})

test('Kimi preset writes the key as a secret and URL/model as plain values', () => {
  const kimi = presetById('kimi-coding')
  const writes = serviceWrites({ provider: kimi.id, key: ' sk-abc ', baseUrl: kimi.baseUrl, model: kimi.model, prefix: '' }, new Set())
  assert.deepEqual(writes, [
    { op: 'save', name: 'OPENAI_API_KEY', value: 'sk-abc', secret: true },
    { op: 'save', name: 'OPENAI_BASE_URL', value: 'https://api.kimi.com/coding/v1', secret: false },
    { op: 'save', name: 'OPENAI_MODEL', value: 'kimi-for-coding', secret: false },
  ])
  assert.equal(newVariableCount(writes!, new Set(['OPENAI_BASE_URL'])), 2)
})

test('editing keeps the stored key, clears a removed model, and refuses incomplete forms', () => {
  const existing = new Set(['OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_MODEL'])
  assert.deepEqual(serviceWrites({ provider: 'openai', key: '', baseUrl: 'https://api.openai.com/v1', model: '', prefix: '' }, existing), [
    { op: 'save', name: 'OPENAI_BASE_URL', value: 'https://api.openai.com/v1', secret: false },
    { op: 'delete', name: 'OPENAI_MODEL' },
  ])
  assert.equal(serviceWrites({ provider: 'custom', key: 'k', baseUrl: '', model: '', prefix: '' }, new Set()), null)
  assert.equal(serviceWrites({ provider: 'custom', key: 'k', baseUrl: 'http://x', model: '', prefix: '' }, new Set()), null)
  assert.equal(serviceWrites({ provider: 'deepseek', key: '', baseUrl: 'https://api.deepseek.com', model: '', prefix: 'DS' }, existing), null)
})

test('configured services group variables by prefix and name the provider', () => {
  const services = configuredServices([
    v('KIMI_API_KEY', null, true, 'wxyz'), v('KIMI_BASE_URL', 'https://api.kimi.ai/coding/v1'), v('KIMI_MODEL', 'k3'),
    v('OPENAI_BASE_URL', 'https://api.deepseek.com/'), v('OPENAI_API_KEY', null, true, '1234'),
    v('MY_API_KEY', null, true, '9999'), v('MY_BASE_URL', 'https://llm.example.org/v1'), v('OTHER', 'x'),
  ])
  assert.deepEqual(services.map(s => [s.prefix, s.label, s.model, s.hint]), [
    ['OPENAI', 'DeepSeek', '', '1234'],
    ['KIMI', 'Kimi Coding Plan', 'k3', 'wxyz'],
    ['MY', 'llm.example.org', '', '9999'],
  ])
})
