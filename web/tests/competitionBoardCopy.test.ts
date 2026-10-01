import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

// Competition numbers as configured for the phases (scripts/configure-v4-phases.py) and stated on the Rules page:
// online cards A–D, 900 s per card, 4 evaluations per team per day; final ranking = mean over the hidden cards E–H.
const load = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/${locale}.json`, import.meta.url), 'utf8'))
const get = (o: any, path: string) => path.split('.').reduce((v, k) => v?.[k], o)
const KEYS = ['leaderboard.public_board', 'leaderboard.final_board', 'leaderboard.mean_note', 'leaderboard.detail.board_mean',
  'home.leaderboard.lede', 'home.submission.items.1.desc', 'faq.items.5.a', 'faq.items.7.a', 'faq.items.8.a']

test('competition copy describes cards A-D, 900 s, 4 evaluations a day and the hidden cards E-H', () => {
  for (const [locale, perDay] of [['en', /4 evaluations per team per day/], ['zh', /每队每天 4 次评测/]] as const) {
    const m = load(locale)
    const text = KEYS.map(k => String(get(m, k))).join('\n')
    assert.match(get(m, 'leaderboard.public_board'), /A–D/)
    assert.match(get(m, 'leaderboard.public_board'), /900/)
    assert.match(get(m, 'leaderboard.final_board'), /E–H/)
    assert.match(get(m, 'faq.items.7.a'), perDay)
    assert.match(get(m, 'faq.items.5.a'), /900/)
    assert.doesNotMatch(text, /three|三个|3600 s per scenario|每个场景 3600|10 (complete )?batches|10 个完整批次|hidden scenario|隐藏(决赛)?场景/)
  }
})
