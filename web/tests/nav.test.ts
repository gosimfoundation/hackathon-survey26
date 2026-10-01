import assert from 'node:assert/strict'
import test from 'node:test'
import { mainNavItems, moreNavItems, participateItem } from '../src/lib/nav.ts'

test('the header keeps three main links plus the prominent Participate button', () => {
  assert.deepEqual(mainNavItems.map(item => item.to), ['/start', '/rules', '/leaderboard'])
  assert.deepEqual(participateItem, { key: 'nav.submit', to: '/compete' })
})

test('every former header page stays reachable under More', () => {
  assert.deepEqual(moreNavItems.map(item => item.to),
    ['/brief', '/cards', '/docs', '/resources', '/faq', '/announcements', '/teammates'])
  const all = new Set([...mainNavItems, participateItem, ...moreNavItems].map(item => item.to))
  for (const path of ['/start', '/brief', '/rules', '/cards', '/docs', '/resources', '/faq', '/leaderboard', '/announcements', '/teammates', '/compete']) {
    assert.ok(all.has(path), `${path} must stay reachable from the header`)
  }
})
