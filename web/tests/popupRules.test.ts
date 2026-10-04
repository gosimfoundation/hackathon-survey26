import assert from 'node:assert/strict'
import test from 'node:test'
import { announcementKey, contentHash, kimiPlanKey, parseSeenList, pickPopup, rememberSeenList } from '../src/lib/popupRules.ts'

test('one popup per page load: the most important candidate wins, whatever the asking order', () => {
  assert.equal(pickPopup([]), null)
  assert.equal(pickPopup(['kimi-plan', 'pinned-announcement']), 'pinned-announcement')
  assert.equal(pickPopup(['pinned-announcement', 'quota-reset', 'team-requests']), 'team-requests')
  assert.equal(pickPopup(['kimi-plan', 'browser-notice']), 'browser-notice')
  assert.equal(pickPopup(['something-new', 'kimi-plan']), 'kimi-plan')
})

test('an announcement key changes only when its content changes', () => {
  const a = { id: 7, title_en: 'Hi', title_zh: '你好', body_en: 'x', body_zh: 'y', created_at: '2026-10-04', is_pinned: true }
  assert.equal(announcementKey(a), announcementKey({ ...a, created_at: '2026-10-05', is_pinned: false }))
  assert.notEqual(announcementKey(a), announcementKey({ ...a, body_zh: 'y!' }))
  assert.notEqual(announcementKey(a), announcementKey({ ...a, id: 8 }))
  assert.match(announcementKey(a), /^ann:7:[0-9a-f]{8}$/)
  assert.notEqual(contentHash('ab', 'c'), contentHash('a', 'bc'))
  assert.notEqual(kimiPlanKey('t', 'member'), kimiPlanKey('t', 'captain'))
})

test('the seen list survives junk, keeps the newest and has no duplicates', () => {
  assert.deepEqual(parseSeenList('not json'), [])
  assert.deepEqual(parseSeenList(null), [])
  assert.deepEqual(parseSeenList('{"a":1}'), [])
  assert.deepEqual(rememberSeenList(['a', 'b'], ['a', 'c', 'c']), ['b', 'a', 'c'])
  const big = Array.from({ length: 400 }, (_, i) => `k${i}`)
  const kept = rememberSeenList(big, ['new'])
  assert.equal(kept.length, 300)
  assert.equal(kept.at(-1), 'new')
})
