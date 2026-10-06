import assert from 'node:assert/strict'
import test from 'node:test'
import { cached, invalidatePrefix } from '../src/lib/requestCache.ts'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

for (const oldFinishesFirst of [true, false]) {
  test(`invalidation keeps the replacement request when old finishes ${oldFinishesFirst ? 'first' : 'last'}`, async () => {
    const key = `board:completion-${oldFinishesFirst}`
    const old = deferred<string>()
    const fresh = deferred<string>()
    let calls = 0
    const fetch = () => ++calls === 1 ? old.promise : fresh.promise
    const first = cached(key, 60_000, fetch)
    invalidatePrefix('board:')
    const second = cached(key, 60_000, fetch)
    assert.equal(calls, 2)

    if (oldFinishesFirst) {
      old.resolve('old')
      assert.equal(await first, 'old')
      const shared = cached(key, 60_000, fetch)
      fresh.resolve('fresh')
      assert.equal(await shared, 'fresh')
    } else {
      fresh.resolve('fresh')
      assert.equal(await second, 'fresh')
      old.resolve('old')
    }

    assert.equal(await first, 'old')
    assert.equal(await second, 'fresh')
    assert.equal(await cached(key, 60_000, fetch), 'fresh')
    assert.equal(calls, 2)
    invalidatePrefix('board:')
  })
}

test('storage invalidation also detaches pending requests', async () => {
  const values: Record<string, string> = {}
  const store = Object.defineProperties(values, {
    getItem: { value: (key: string) => values[key] ?? null },
    setItem: { value: (key: string, value: string) => { values[key] = value } },
    removeItem: { value: (key: string) => { delete values[key] } },
  }) as unknown as Storage
  const key = 'board:storage'
  const old = deferred<string>()
  const first = cached(key, 60_000, () => old.promise, store)
  invalidatePrefix('board:', store)
  const second = cached(key, 60_000, async () => 'fresh', store)
  old.resolve('old')
  assert.equal(await second, 'fresh')
  assert.equal(await first, 'old')
  assert.equal(await cached(key, 60_000, async () => 'unexpected', store), 'fresh')
  invalidatePrefix('board:', store)
  assert.equal(store.getItem(key), null)
})
