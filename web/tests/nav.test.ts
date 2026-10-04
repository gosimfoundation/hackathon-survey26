import assert from 'node:assert/strict'
import test from 'node:test'
import { mainNavItems, moreNavItems, participateItem } from '../src/lib/nav.ts'

test('the header keeps its main links, ends with About, plus the prominent Participate button', () => {
  assert.deepEqual(mainNavItems.map(item => item.to), ['/start', '/rules', '/leaderboard', '/teammates', '/about'])
  assert.deepEqual(participateItem, { key: 'nav.submit', to: '/compete' })
})

test('every former header page stays reachable under More', () => {
  assert.deepEqual(moreNavItems.map(item => item.to),
    ['/brief', '/cards', '/docs', '/resources', '/faq', '/announcements'])
  const all = new Set([...mainNavItems, participateItem, ...moreNavItems].map(item => item.to))
  for (const path of ['/about', '/start', '/brief', '/rules', '/cards', '/docs', '/resources', '/faq', '/leaderboard', '/announcements', '/teammates', '/compete']) {
    assert.ok(all.has(path), `${path} must stay reachable from the header`)
  }
})

test('below 1280px the wide main links still have a place under More', () => {
  assert.deepEqual(mainNavItems.filter(item => item.wide).map(item => item.to), ['/teammates', '/about'])
})
