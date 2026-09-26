import assert from 'node:assert/strict'
import test from 'node:test'
import { canChooseFinal, canClearFinal, canWithdraw, countedEvaluations, finalRole, finalVersionFor, recentDuplicate, visibleProjects, withdrawnCount } from '../src/lib/projectEvaluation.ts'

const batches = [
  { revision_id: 'a', phase_id: 'p', status: 'scored', quota_refunded: false },
  { revision_id: 'a', phase_id: 'p', status: 'failed', quota_refunded: true },
  { revision_id: 'a', phase_id: 'other', status: 'scored' },
  { revision_id: 'b', phase_id: 'p', status: 'failed', quota_refunded: true },
]

test('only counted evaluations of the same version and phase make a repeat', () => {
  assert.equal(countedEvaluations(batches, 'a', 'p'), 1)
  assert.equal(countedEvaluations(batches, 'b', 'p'), 0)
  assert.equal(countedEvaluations(null, 'a', 'p'), 0)
})

test('evaluated, withdrawn and preparing versions cannot be withdrawn', () => {
  for (const status of ['queued', 'reviewable', 'failed', 'approved']) assert.ok(canWithdraw({ id: 'c', status }, batches), status)
  assert.ok(!canWithdraw({ id: 'c', status: 'preparing' }, batches))
  assert.ok(!canWithdraw({ id: 'b', status: 'approved' }, batches))
  assert.ok(!canWithdraw({ id: 'c', status: 'approved', archived_at: '2026-09-27T00:00:00Z' }, batches))
})

test('withdrawn versions are hidden until requested', () => {
  const projects = [
    { title: 'One', observer_revisions: [{ id: '1', status: 'approved', archived_at: '2026-09-27T00:00:00Z' }] },
    { title: 'Two', observer_revisions: [{ id: '2', status: 'reviewable' }] },
  ]
  assert.deepEqual(visibleProjects(projects, false).map(p => p.title), ['Two'])
  assert.deepEqual(visibleProjects(projects, true).map(p => p.title), ['One', 'Two'])
  assert.equal(withdrawnCount(projects), 1)
})

test('a resubmission of the same project within minutes is recognized', () => {
  const now = Date.parse('2026-09-27T10:00:00Z')
  const projects = [
    { title: 'Agent', observer_revisions: [{ id: '1', status: 'queued', source_kind: 'repository', source_location: 'https://github.com/Owner/Repo', created_at: '2026-09-27T09:57:00Z' }] },
    { title: 'Zip', observer_revisions: [{ id: '2', status: 'queued', source_kind: 'zip', source_location: 't/u/source.zip', created_at: '2026-09-27T09:58:00Z' }] },
  ]
  assert.ok(recentDuplicate(projects, ' Agent ', 'https://github.com/owner/repo.git/', now))
  assert.ok(!recentDuplicate(projects, 'Agent', 'https://github.com/owner/other', now))
  assert.ok(!recentDuplicate(projects, 'Other', 'https://github.com/owner/repo', now))
  assert.ok(!recentDuplicate(projects, 'Agent', 'https://github.com/owner/repo', now + 20 * 60_000))
  assert.ok(recentDuplicate(projects, 'Zip', null, now))
  assert.ok(!recentDuplicate(projects, 'Agent', null, now))
})

test('the final version: chosen or default, changeable until the deadline', () => {
  const base = { deadline: '2026-10-07T15:59:00Z', locked: false, chosen_by: null, chosen_at: null, best_batch_id: 'b1', best_revision_id: 'r1', best_score: 12 }
  const defaulted = { ...base, phase_id: 'online', revision_id: 'r1', source: 'best' as const, chosen_revision_id: null }
  const chosen = { ...base, phase_id: 'other', revision_id: 'r2', source: 'chosen' as const, chosen_revision_id: 'r2' }
  const before = Date.parse('2026-10-06T00:00:00Z'), after = Date.parse('2026-10-07T16:00:00Z')
  assert.equal(finalVersionFor([chosen, defaulted], 'online'), defaulted)
  assert.equal(finalVersionFor([chosen, defaulted], 'missing'), chosen)
  assert.equal(finalVersionFor(null, 'online'), null)
  assert.equal(finalRole(defaulted, 'r1'), 'best')
  assert.equal(finalRole(chosen, 'r2'), 'chosen')
  assert.equal(finalRole(chosen, 'r1'), null)
  assert.ok(canChooseFinal(defaulted, 'r1', before))
  assert.ok(!canChooseFinal(chosen, 'r2', before))
  assert.ok(canChooseFinal(chosen, 'r1', before))
  assert.ok(!canChooseFinal(chosen, 'r1', after))
  assert.ok(!canChooseFinal({ ...chosen, locked: true }, 'r1', before))
  assert.ok(canClearFinal(chosen, before) && !canClearFinal(defaulted, before) && !canClearFinal(chosen, after))
  assert.ok(!canChooseFinal(null, 'r1', before) && !canClearFinal(null, before))
})
