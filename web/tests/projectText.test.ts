import assert from 'node:assert/strict'
import test from 'node:test'
import { canPrepareAgain, formatDailyReset, formatDateTime, revisionErrorText } from '../src/lib/projectText.ts'

test('dates follow the page language instead of the browser default', () => {
  const value = '2026-09-26T11:00:37Z'
  assert.equal(formatDateTime(value, 'zh', 'Asia/Shanghai'), '2026/09/26 19:00')
  assert.match(formatDateTime(value, 'en', 'Asia/Shanghai'), /^09\/26\/2026,? 19:00$/)
  assert.ok(!formatDateTime(value, 'zh', 'UTC').includes('PM'))
  assert.equal(formatDateTime(null, 'zh'), '—')
  assert.equal(formatDateTime('not a date', 'en'), '—')
})

test('the daily reset names its time zone', () => {
  assert.equal(formatDailyReset('2026-09-27T00:00:00Z', 'zh'), '每天 UTC 0:00（北京时间 8:00）重置')
  assert.equal(formatDailyReset('2026-09-27T00:00:00Z', 'en'), 'Resets daily at 0:00 UTC (8:00 Beijing time)')
  assert.equal(formatDailyReset(undefined, 'zh'), '每天 UTC 0:00（北京时间 8:00）重置')
  assert.equal(formatDailyReset('2026-09-27T20:30:00Z', 'zh'), '每天 UTC 20:30（北京时间 4:30）重置')
})

test('preparation errors are shown in Chinese on the zh page', () => {
  assert.equal(revisionErrorText('Project preparation failed. Please retry.', 'zh'), '项目准备失败，请修正后重新上传。')
  assert.equal(revisionErrorText('Project preparation failed: Automatic adaptation could not identify the entry point.', 'zh'),
    '项目准备失败：Automatic adaptation could not identify the entry point.')
  assert.equal(revisionErrorText('Public test failed. Check the project interface and submit again.', 'zh'), '公开场景测试未通过，请检查项目接口后重新上传。')
  assert.equal(revisionErrorText('Project preparation failed. Please retry.', 'en'), 'Project preparation failed. Please retry.')
  assert.equal(revisionErrorText('Something else', 'zh'), 'Something else')
  assert.equal(revisionErrorText(null, 'zh'), '')
})

test('only failed public repositories can be prepared again from the same source', () => {
  const repo = { status: 'failed', source_kind: 'repository', source_location: 'https://github.com/team/project' }
  assert.ok(canPrepareAgain(repo))
  assert.ok(!canPrepareAgain({ ...repo, status: 'reviewable' }))
  assert.ok(!canPrepareAgain({ ...repo, archived_at: '2026-09-27T00:00:00Z' }))
  assert.ok(!canPrepareAgain({ status: 'failed', source_kind: 'zip', source_location: 'uploads/x/source.zip' }))
})
