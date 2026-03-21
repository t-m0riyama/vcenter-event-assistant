import { describe, expect, it } from 'vitest'

import { pickMetricKeyAfterFetch } from './fetchMetricKeys'

describe('pickMetricKeyAfterFetch', () => {
  it('keeps previous when present in list', () => {
    expect(
      pickMetricKeyAfterFetch('host.cpu.usage_pct', [
        'a',
        'host.cpu.usage_pct',
        'b',
      ]),
    ).toBe('host.cpu.usage_pct')
  })

  it('falls back to first key', () => {
    expect(pickMetricKeyAfterFetch('missing', ['a', 'b'])).toBe('a')
  })

  it('returns empty when list is empty', () => {
    expect(pickMetricKeyAfterFetch('any', [])).toBe('')
  })
})
