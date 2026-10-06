import assert from 'node:assert/strict'
import test from 'node:test'
import { ANNOUNCEMENT_CLOSES, announcementCloseKey, announcementCloses, contentHash, pickAnnouncement, kimiPlanKey, parseSeenList, pickPopup, rememberSeenList } from '../src/lib/popupRules.ts'

test('one popup per page load: the most important candidate wins, whatever the asking order', () => {
  assert.equal(pickPopup([]), null)
  assert.equal(pickPopup(['kimi-plan', 'pinned-announcement']), 'pinned-announcement')
  assert.equal(pickPopup(['pinned-announcement', 'quota-reset', 'team-requests']), 'team-requests')
  assert.equal(pickPopup(['kimi-plan', 'browser-notice']), 'browser-notice')
  assert.equal(pickPopup(['something-new', 'kimi-plan']), 'kimi-plan')
})

test('an announcement pops up until closed 3 times; only notify_version brings it back, with a fresh count', () => {
  const a = { id: 7, title_en: 'Hi', body_zh: 'y', created_at: '2026-10-04', is_pinned: true }
  const seen = new Set<string>()
  assert.equal(announcementCloses(a, seen), 0)
  for (let n = 1; n <= ANNOUNCEMENT_CLOSES; n++) {
    assert.equal(pickAnnouncement([a], seen), a)
    seen.add(announcementCloseKey(a, n))
    assert.equal(announcementCloses(a, seen), n)
  }
  assert.equal(ANNOUNCEMENT_CLOSES, 3)
  assert.equal(pickAnnouncement([a], seen), null)
  // Text edits keep the keys; "remind everyone" (notify_version + 1) starts again from 0 closes.
  assert.equal(announcementCloseKey({ ...a, body_zh: 'edited' }, 2), 'ann-off:7:v1#close2')
  const reminded = { ...a, notify_version: 2 }
  assert.equal(announcementCloses(reminded, seen), 0)
  assert.equal(pickAnnouncement([reminded], seen), reminded)
})

test('keys of the older snooze / switch-off scheme do not suppress it', () => {
  const a = { id: 7 }
  const old = new Set(['ann:7:v1', 'ann:7:1a2b3c4d', 'ann-off:7:v1', 'ann-snooze:7:v1:2026-10-06'])
  assert.equal(announcementCloses(a, old), 0)
  assert.equal(pickAnnouncement([a], old), a)
})

test('one announcement per page load, rotating: the least-closed one shows, newest first on a tie', () => {
  const rows = [{ id: 3 }, { id: 2 }, { id: 1 }]
  const seen = new Set<string>([1, 2, 3].map(n => announcementCloseKey(rows[1]!, n)))
  assert.equal(pickAnnouncement(rows, seen)?.id, 3)
  seen.add(announcementCloseKey(rows[0]!, 1))
  assert.equal(pickAnnouncement(rows, seen)?.id, 1)
  seen.add(announcementCloseKey(rows[2]!, 1))
  assert.equal(pickAnnouncement(rows, seen)?.id, 3)
  for (const r of [rows[0]!, rows[2]!]) for (const n of [2, 3]) seen.add(announcementCloseKey(r, n))
  assert.equal(pickAnnouncement(rows, seen), null)
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
