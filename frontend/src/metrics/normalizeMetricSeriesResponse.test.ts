import { describe, expect, it } from 'vitest'

import { normalizeMetricSeriesResponse } from './normalizeMetricSeriesResponse'

describe('normalizeMetricSeriesResponse', () => {
  it('returns empty series for null, undefined, or non-object', () => {
    expect(normalizeMetricSeriesResponse(null)).toEqual({ points: [], total: 0 })
    expect(normalizeMetricSeriesResponse(undefined)).toEqual({ points: [], total: 0 })
    expect(normalizeMetricSeriesResponse('x')).toEqual({ points: [], total: 0 })
    expect(normalizeMetricSeriesResponse(1)).toEqual({ points: [], total: 0 })
  })

  it('returns empty points and zero total for empty object', () => {
    expect(normalizeMetricSeriesResponse({})).toEqual({ points: [], total: 0 })
  })

  it('uses empty points when points is not an array but keeps finite total', () => {
    expect(
      normalizeMetricSeriesResponse({
        points: 'not-array',
        total: 3,
      }),
    ).toEqual({ points: [], total: 3 })
  })

  it('normalizes total to 0 when missing, NaN, or non-finite number', () => {
    expect(normalizeMetricSeriesResponse({ points: [], total: NaN })).toEqual({
      points: [],
      total: 0,
    })
    expect(normalizeMetricSeriesResponse({ points: [], total: '5' } as unknown)).toEqual({
      points: [],
      total: 0,
    })
  })

  it('preserves valid points and total', () => {
    const points = [
      {
        sampled_at: '2024-01-01T00:00:00Z',
        value: 1,
        entity_name: 'h',
        metric_key: 'k',
        vcenter_id: '00000000-0000-0000-0000-000000000000',
      },
    ]
    expect(normalizeMetricSeriesResponse({ points, total: 2 })).toEqual({ points, total: 2 })
  })
})
