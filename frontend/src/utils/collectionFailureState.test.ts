import { describe, expect, it } from 'vitest'

import { getCollectionFailureState } from './collectionFailureState'

describe('getCollectionFailureState', () => {
  it.each([
    [null, '2026-13-01T00:00:00.123456Z'],
    ['2026-11-26T00:00:00Z', '2026-13-01T00:00:00.123456Z'],
    ['2026-13-01T00:00:00.123456Z', '2026-11-26T00:00:00Z'],
  ])('成功時刻が %s、失敗時刻が %s の場合は状態を判定できない', (success, failure) => {
    expect(getCollectionFailureState(success, failure)).toBe('unknown')
  })
})
