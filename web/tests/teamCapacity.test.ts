import assert from 'node:assert/strict'
import test from 'node:test'
import { parseTeamCapacity, teamCreationBlocked } from '../src/lib/teamCapacity.ts'

test('capacity is derived from the limit and the visible team count', () => {
  assert.deepEqual(parseTeamCapacity({ limit: 150, teams: 94, remaining: 56, full: false }), { limit: 150, teams: 94, remaining: 56, full: false })
  assert.deepEqual(parseTeamCapacity({ limit: 150, teams: 150 }), { limit: 150, teams: 150, remaining: 0, full: true })
  assert.deepEqual(parseTeamCapacity({ limit: 150, teams: 151 }), { limit: 150, teams: 151, remaining: 0, full: true })
})

test('a malformed payload is unknown, never full', () => {
  for (const bad of [null, undefined, 'full', [], {}, { limit: '150', teams: 3 }, { limit: 150, teams: -1 }, { limit: 1.5, teams: 0 }]) {
    assert.equal(parseTeamCapacity(bad), null)
  }
  assert.equal(teamCreationBlocked(null, false), false)
})

test('only non-admins are blocked when every place is taken', () => {
  const full = parseTeamCapacity({ limit: 2, teams: 2 })
  const open = parseTeamCapacity({ limit: 2, teams: 1 })
  assert.equal(teamCreationBlocked(full, false), true)
  assert.equal(teamCreationBlocked(full, undefined), true)
  assert.equal(teamCreationBlocked(full, true), false)
  assert.equal(teamCreationBlocked(open, false), false)
})
