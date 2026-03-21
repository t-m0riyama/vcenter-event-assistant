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

  it('drops points with invalid sampled_at (null, empty, or unparsable)', () => {
    const valid = {
      sampled_at: '2024-01-01T00:00:00Z',
      value: 10,
      entity_name: 'host',
      metric_key: 'k',
      vcenter_id: '00000000-0000-0000-0000-000000000000',
    }
    expect(
      normalizeMetricSeriesResponse({
        points: [
          valid,
          { ...valid, sampled_at: null },
          { ...valid, sampled_at: '' },
          { ...valid, sampled_at: 'not-a-date' },
        ],
        total: 4,
      }),
    ).toEqual({ points: [valid], total: 4 })
  })

  it('drops points with non-string entity_name, metric_key, or vcenter_id', () => {
    const valid = {
      sampled_at: '2024-01-01T00:00:00Z',
      value: 5,
      entity_name: 'e',
      metric_key: 'm',
      vcenter_id: 'vc',
    }
    expect(
      normalizeMetricSeriesResponse({
        points: [
          valid,
          { ...valid, entity_name: null },
          { ...valid, metric_key: undefined },
          { ...valid, vcenter_id: 123 },
        ],
        total: 4,
      }),
    ).toEqual({ points: [valid], total: 4 })
  })

  it('drops points with non-finite value', () => {
    const valid = {
      sampled_at: '2024-01-01T00:00:00Z',
      value: 1,
      entity_name: 'e',
      metric_key: 'm',
      vcenter_id: 'v',
    }
    expect(
      normalizeMetricSeriesResponse({
        points: [valid, { ...valid, value: NaN }, { ...valid, value: '1' }],
        total: 3,
      }),
    ).toEqual({ points: [valid], total: 3 })
  })
})
