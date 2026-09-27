import assert from 'node:assert/strict'
import test from 'node:test'
import { kimiPlanState, normalizeKimiPlanStatus } from '../src/lib/kimiPlan.ts'

const base = { has_team: true, is_captain: true, hidden: false, qualified: true, eligible: true, imported: true, available: 3, code: null, note: '', claimed_at: null, claimed_by: null }

test('the backend payload is normalized defensively', () => {
  const s = normalizeKimiPlanStatus({ has_team: true, available: '2', code: '', claimed_by: '' })
  assert.equal(s.available, 2)
  assert.equal(s.code, null)
  assert.equal(s.claimed_by, null)
  assert.equal(s.eligible, false)
  assert.equal(normalizeKimiPlanStatus(null).has_team, false)
})

test('before codes are imported the panel says they are coming, whatever the eligibility', () => {
  assert.equal(kimiPlanState({ ...base, imported: false, available: 0 }), 'coming_soon')
  assert.equal(kimiPlanState({ ...base, imported: false, available: 0, eligible: false }), 'coming_soon')
})

test('only the captain of an eligible team gets the claim button', () => {
  assert.equal(kimiPlanState(base), 'claimable')
  assert.equal(kimiPlanState({ ...base, is_captain: false }), 'wait_captain')
  assert.equal(kimiPlanState({ ...base, eligible: false }), 'not_eligible')
  assert.equal(kimiPlanState({ ...base, available: 0 }), 'sold_out')
})

test('a claimed code is shown to every member, even after the pool runs out', () => {
  assert.equal(kimiPlanState({ ...base, code: 'k-1', available: 0, is_captain: false }), 'claimed')
  assert.equal(kimiPlanState({ ...base, has_team: false }), 'no_team')
})
