import assert from 'node:assert/strict'
import test from 'node:test'
import { cardBoardTabs, parseCardBoard, pickCardTab, toLeaderboardEntry } from '../src/lib/cardBoard.ts'

const cards = [{ slug: 'card-a', name: 'Card A' }, { slug: 'card-b', name: 'Card B' }]

test('overall boards have no tabs; card layouts list the cards, with overall first where ranked', () => {
  assert.deepEqual(cardBoardTabs({ layout: 'overall', cards }), [])
  assert.deepEqual(cardBoardTabs({ layout: 'cards', cards }), ['card-a', 'card-b'])
  assert.deepEqual(cardBoardTabs({ layout: 'cards_overall', cards }), [null, 'card-a', 'card-b'])
  // A sealed or not yet open phase returns no card names: no tabs at all.
  assert.deepEqual(cardBoardTabs({ layout: 'cards_overall', cards: [] }), [])
})

test('the requested tab is kept when present, otherwise the first tab is used', () => {
  assert.equal(pickCardTab({ layout: 'cards_overall', cards }, 'card-b'), 'card-b')
  assert.equal(pickCardTab({ layout: 'cards_overall', cards }, null), null)
  assert.equal(pickCardTab({ layout: 'cards_overall', cards }, 'gone'), null)
  assert.equal(pickCardTab({ layout: 'cards', cards }, null), 'card-a')
  assert.equal(pickCardTab({ layout: 'cards', cards }, 'gone'), 'card-a')
  assert.equal(pickCardTab({ layout: 'overall', cards: [] }, 'card-a'), null)
})

test('card board rows keep the observer_board fields and add card scores and components', () => {
  const board = parseCardBoard({
    layout: 'cards_overall', scenario: null, cards: [...cards, { slug: 'no-name' }, null],
    rows: [{ rank: 1, team_id: 't1', team_name: 'Team', total_score: 40, submission_count: 2, kind: 'observer',
      card_scores: { 'card-a': 30, 'card-b': 50, bad: 'x' }, overall_score: 40, overall_rank: 1, targets_observed: null,
      components: { sum_best_scores: 50, required_penalty: -6, note: 'text' }, required_missing: 1 }],
  })
  assert.equal(board.layout, 'cards_overall')
  assert.deepEqual(board.cards.map(c => c.name), ['Card A', 'Card B', 'no-name'])
  const [row] = board.rows
  assert.deepEqual(row!.card_scores, { 'card-a': 30, 'card-b': 50 })
  assert.deepEqual(row!.components, { sum_best_scores: 50, required_penalty: -6 })
  assert.equal(row!.targets_observed, null)
  assert.equal(row!.required_missing, 1)
  assert.equal(parseCardBoard({ layout: 'something-else' }).layout, 'overall')
})

test('v3 board rows map exactly as before (no card fields)', () => {
  const row = toLeaderboardEntry({ team_id: 't', total_score: '12.5', completed_tiles: null, coverage_bonus: 0 }, 3)
  assert.equal(row.rank, 4)
  assert.equal(row.total_score, 12.5)
  assert.equal(row.completed_tiles, null)
  assert.equal(row.coverage_bonus, 0)
  assert.ok(!('card_scores' in row) && !('components' in row))
})
