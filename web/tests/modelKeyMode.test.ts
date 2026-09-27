import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { DEFAULT_MODEL_KEY_MODE, relayMissesHiddenFinal, teamModelMode } from '../src/lib/modelKeyMode.ts'

test('not saving the key is the default; saving is an explicit opt-in', () => {
  assert.equal(DEFAULT_MODEL_KEY_MODE, 'relay')
  assert.equal(teamModelMode(null), 'relay')
  assert.equal(teamModelMode(undefined), 'relay')
  assert.equal(teamModelMode({}), 'relay')
  assert.equal(teamModelMode({ mode: 'relay' }), 'relay')
  assert.equal(teamModelMode({ mode: 'unknown' }), 'relay')
  assert.equal(teamModelMode({ mode: 'stored' }), 'stored')
})

test('every locale explains the trade-off and marks not saving as the default', () => {
  const marks: Record<string, string> = { zh: '默认', en: 'default', fr: 'par défaut', ja: '既定' }
  for (const [lang, mark] of Object.entries(marks)) {
    const words = JSON.parse(readFileSync(new URL(`../src/i18n/${lang}.json`, import.meta.url), 'utf8')).submit.model_api
    for (const key of ['tradeoff', 'relay', 'relay_help', 'stored', 'stored_help']) assert.ok(words[key]?.trim(), `${lang}.${key}`)
    assert.ok(words.relay.includes(mark), `${lang}: the relay option is labelled as the default`)
    assert.ok(!/推荐|recommended|recommandé|推奨/i.test(words.stored), `${lang}: saving is not recommended over the default`)
  }
  // One plain sentence per language, naming both choices.
  const zh = JSON.parse(readFileSync(new URL('../src/i18n/zh.json', import.meta.url), 'utf8')).submit.model_api
  assert.equal(zh.tradeoff, '不保存：评测时需保持页面打开；保存：加密存储，成绩核实后自动删除。')
})

test('relay teams are warned that the hidden final cannot use their key', () => {
  assert.equal(relayMissesHiddenFinal('relay', true), true)
  assert.equal(relayMissesHiddenFinal('stored', true), false)
  assert.equal(relayMissesHiddenFinal('relay', false), false)
  const view = readFileSync(new URL('../src/components/competition/ProjectWorkflow.vue', import.meta.url), 'utf8')
  assert.ok(view.includes('如果你的程序会调用大模型，请在比赛结束前把模型 API 改为『加密保存』，否则最终隐藏场景评测时模型调用会失败。'))
  assert.ok(view.includes('data-testid="final-version-relay-warning"') && view.includes('data-testid="model-mode-final-note"'))
})
