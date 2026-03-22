import { describe, expect, it } from 'vitest'
import {
  formatChartTooltipNumber,
  formatChartYAxisTick,
  getMetricStorageScale,
  metricValueToBytes,
} from './chartYAxisFormat'

describe('formatChartYAxisTick', () => {
  it('metric: keeps small decimals as-is', () => {
    expect(formatChartYAxisTick(3.14, 'metric')).toBe('3.14')
    expect(formatChartYAxisTick(-2.5, 'metric')).toBe('-2.5')
  })

  it('metric: groups rounded integers below compact threshold', () => {
    expect(formatChartYAxisTick(42, 'metric')).toBe('42')
    expect(formatChartYAxisTick(9999, 'metric')).toBe('9,999')
  })

  it('metric: uses compact notation at threshold and above', () => {
    expect(formatChartYAxisTick(10_000, 'metric')).toMatch(/万/)
    expect(formatChartYAxisTick(1_234_567, 'metric')).toMatch(/万/)
  })

  it('count: groups integers below compact threshold', () => {
    expect(formatChartYAxisTick(0, 'count')).toBe('0')
    expect(formatChartYAxisTick(1234, 'count')).toBe('1,234')
  })

  it('count: uses compact notation for large values', () => {
    expect(formatChartYAxisTick(50_000, 'count')).toMatch(/万/)
  })

  it('returns empty string for non-finite', () => {
    expect(formatChartYAxisTick(Number.NaN, 'metric')).toBe('')
    expect(formatChartYAxisTick(Number.POSITIVE_INFINITY, 'count')).toBe('')
  })
})

describe('getMetricStorageScale', () => {
  it('detects suffix order (longer *bytes before _bytes)', () => {
    expect(getMetricStorageScale('datastore.space.used_bytes')).toBe('bytes')
    expect(getMetricStorageScale('x_kbytes')).toBe('kbytes')
    expect(getMetricStorageScale('x_mbytes')).toBe('mbytes')
    expect(getMetricStorageScale('pool.size_tbytes')).toBe('tbytes')
    expect(getMetricStorageScale('pool.size_pbytes')).toBe('pbytes')
    expect(getMetricStorageScale('dc.total_ybytes')).toBe('ybytes')
  })

  it('returns null for non-storage keys', () => {
    expect(getMetricStorageScale('host.cpu.usage_pct')).toBe(null)
  })
})

describe('metricValueToBytes', () => {
  it('scales by SI exponents (1000^exp)', () => {
    expect(metricValueToBytes(1, 'kbytes')).toBe(1000)
    expect(metricValueToBytes(2, 'mbytes')).toBe(2 * 1000 * 1000)
    expect(metricValueToBytes(1, 'tbytes')).toBe(1000 ** 4)
    expect(metricValueToBytes(1, 'ybytes')).toBe(1000 ** 8)
  })
})

describe('formatChartYAxisTick storage metrics', () => {
  it('formats bytes with K/M/G/T suffixes on axis (SI 1000, not 万/億)', () => {
    expect(formatChartYAxisTick(1536, 'metric', 'datastore.space.used_bytes')).toMatch(/K/)
    expect(formatChartYAxisTick(1536, 'metric', 'datastore.space.used_bytes')).not.toMatch(/万/)
    expect(formatChartYAxisTick(750 * 1024 * 1024, 'metric', 'datastore.space.used_bytes')).toMatch(
      /M/,
    )
  })

  it('infers scale from key: _kbytes 1000 → 1M, _mbytes 1000 → 1G', () => {
    expect(formatChartYAxisTick(1000, 'metric', 'ds.used_kbytes')).toBe('1M')
    expect(formatChartYAxisTick(1000, 'metric', 'ds.used_mbytes')).toBe('1G')
  })

  it('interprets _kbytes as kilobytes (1000 B per unit)', () => {
    expect(formatChartYAxisTick(1, 'metric', 'ds.used_kbytes')).toBe('1K')
  })

  it('formats T and above from raw bytes or *_tbytes keys', () => {
    expect(formatChartYAxisTick(1, 'metric', 'ds.used_tbytes')).toBe('1T')
    expect(formatChartYAxisTick(10 ** 24, 'metric', 'datastore.space.used_bytes')).toMatch(/Y/)
    expect(formatChartYAxisTick(1, 'metric', 'dc.total_ybytes')).toBe('1Y')
  })
})

describe('formatChartTooltipNumber', () => {
  it('uses storage format for byte metrics and plain for evCount', () => {
    expect(formatChartTooltipNumber(2048, { metricKey: 'datastore.space.used_bytes' })).toMatch(
      /K/,
    )
    expect(formatChartTooltipNumber(42, { metricKey: 'host.cpu.usage_pct' })).toBe('42')
    expect(
      formatChartTooltipNumber(10, {
        metricKey: 'datastore.space.used_bytes',
        dataKey: 'evCount',
      }),
    ).toBe('10')
  })

  it('formats with grouping for readability', () => {
    expect(formatChartTooltipNumber(1234)).toBe('1,234')
    expect(formatChartTooltipNumber(1234567.89)).toMatch(/^1[,.、]?234/)
  })

  it('returns empty string for non-finite', () => {
    expect(formatChartTooltipNumber(Number.NaN)).toBe('')
  })
})
