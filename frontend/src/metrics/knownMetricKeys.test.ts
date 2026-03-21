import { describe, expect, it } from 'vitest'

import { KNOWN_METRIC_KEYS, mergeMetricKeyOptions } from './knownMetricKeys'

describe('mergeMetricKeyOptions', () => {
  it('merges API keys with catalog and sorts', () => {
    const out = mergeMetricKeyOptions(['host.mem.usage_pct', 'z.extra'])
    expect(out[0]).toBe('datastore.space.used_bytes')
    expect(out).toContain('z.extra')
    expect(out.length).toBe(KNOWN_METRIC_KEYS.length + 1)
  })

  it('dedupes', () => {
    const out = mergeMetricKeyOptions(['host.cpu.usage_pct'])
    expect(out.filter((k) => k === 'host.cpu.usage_pct').length).toBe(1)
  })
})
