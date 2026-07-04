import { describe, expect, it } from 'vitest'
import { computeEventRateOverlayRange } from './computeEventRateOverlayRange'
import type { MetricPoint } from './normalizeMetricSeriesResponse'

const point = (sampled_at: string): MetricPoint => ({
  sampled_at,
  value: 1,
  entity_moid: 'h1',
  entity_name: 'ESXi',
  metric_key: 'cpu',
  vcenter_id: 'vc-1',
})

describe('computeEventRateOverlayRange', () => {
  it('uses explicit graph range when set', () => {
    const r = computeEventRateOverlayRange(
      {
        mode: 'range',
        from: '2025-06-15T00:00:00.000Z',
        to: '2025-06-16T00:00:00.000Z',
      },
      [],
      300,
    )
    expect(r).toEqual({
      from: '2025-06-15T00:00:00.000Z',
      to: '2025-06-16T00:00:00.000Z',
    })
  })

  it('derives bounds from metric points when range is none', () => {
    const r = computeEventRateOverlayRange(
      { mode: 'none' },
      [point('2025-06-15T10:00:00.000Z'), point('2025-06-15T12:00:00.000Z')],
      300,
    )
    expect(r).toEqual({
      from: '2025-06-15T10:00:00.000Z',
      to: '2025-06-15T12:00:00.000Z',
    })
  })

  it('extends to when single point makes from >= to', () => {
    const r = computeEventRateOverlayRange(
      { mode: 'none' },
      [point('2025-06-15T10:00:00.000Z')],
      300,
    )
    expect(r).not.toBeNull()
    expect(r!.from).toBe('2025-06-15T10:00:00.000Z')
    expect(r!.to).toBe('2025-06-15T10:05:00.000Z')
  })

  it('returns null for invalid graph range', () => {
    expect(
      computeEventRateOverlayRange({ mode: 'invalid', message: 'x' }, [point('2025-06-15T10:00:00.000Z')], 300),
    ).toBeNull()
  })
})
