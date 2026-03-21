import { describe, expect, it } from 'vitest'

import { buildEventListSearchParams } from './buildEventListQuery'

const emptyFilters = {
  minScore: '',
  filterEventType: '',
  filterSeverity: '',
  filterMessage: '',
  filterComment: '',
} as const

describe('buildEventListSearchParams', () => {
  it('sets limit and offset', () => {
    const q = buildEventListSearchParams({
      limit: 50,
      offset: 100,
      filters: emptyFilters,
      range: {},
    })
    expect(q.get('limit')).toBe('50')
    expect(q.get('offset')).toBe('100')
  })

  it('adds optional filters when non-empty', () => {
    const q = buildEventListSearchParams({
      limit: 20,
      offset: 0,
      filters: {
        minScore: '40',
        filterEventType: 'Vm',
        filterSeverity: 'warn',
        filterMessage: 'fail',
        filterComment: 'note',
      },
      range: {},
    })
    expect(q.get('min_score')).toBe('40')
    expect(q.get('event_type_contains')).toBe('Vm')
    expect(q.get('severity_contains')).toBe('warn')
    expect(q.get('message_contains')).toBe('fail')
    expect(q.get('comment_contains')).toBe('note')
  })

  it('trims text filters', () => {
    const q = buildEventListSearchParams({
      limit: 200,
      offset: 0,
      filters: {
        ...emptyFilters,
        filterEventType: '  x  ',
      },
      range: {},
    })
    expect(q.get('event_type_contains')).toBe('x')
  })

  it('omits empty trimmed filters', () => {
    const q = buildEventListSearchParams({
      limit: 200,
      offset: 0,
      filters: {
        ...emptyFilters,
        filterEventType: '   ',
      },
      range: {},
    })
    expect(q.has('event_type_contains')).toBe(false)
  })

  it('adds from and to when provided', () => {
    const q = buildEventListSearchParams({
      limit: 200,
      offset: 400,
      filters: emptyFilters,
      range: {
        from: '2025-01-01T00:00:00.000Z',
        to: '2025-01-02T00:00:00.000Z',
      },
    })
    expect(q.get('from')).toBe('2025-01-01T00:00:00.000Z')
    expect(q.get('to')).toBe('2025-01-02T00:00:00.000Z')
  })
})
