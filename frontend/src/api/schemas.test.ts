import { describe, expect, it } from 'vitest'
import { normalizeEventListPayload, parseSummary } from './schemas'

describe('normalizeEventListPayload', () => {
  it('parses array responses', () => {
    const { items, total, rawItemCount } = normalizeEventListPayload([
      {
        id: 1,
        vcenter_id: 'a',
        occurred_at: '2025-01-01T00:00:00Z',
        event_type: 't',
        message: 'm',
        severity: null,
        notable_score: 0,
        notable_tags: null,
      },
    ])
    expect(total).toBe(1)
    expect(rawItemCount).toBe(1)
    expect(items[0]?.event_type).toBe('t')
  })

  it('parses envelope with items and total', () => {
    const { items, total, rawItemCount } = normalizeEventListPayload({
      items: [
        {
          id: 2,
          vcenter_id: 'b',
          occurred_at: '2025-01-01T00:00:00Z',
          event_type: 'x',
          message: 'y',
          severity: 'info',
          notable_score: 1,
          notable_tags: ['a'],
        },
      ],
      total: 99,
    })
    expect(total).toBe(99)
    expect(rawItemCount).toBe(1)
    expect(items).toHaveLength(1)
  })

  it('keeps rawItemCount when all rows fail validation (envelope pagination)', () => {
    const { items, total, rawItemCount } = normalizeEventListPayload({
      items: [{ not: 'an event row' }],
      total: 500,
    })
    expect(items).toHaveLength(0)
    expect(total).toBe(500)
    expect(rawItemCount).toBe(1)
  })
})

describe('parseSummary', () => {
  it('parses dashboard summary payload', () => {
    const s = parseSummary({
      vcenter_count: 0,
      events_last_24h: 0,
      notable_events_last_24h: 0,
      top_notable_events: [],
      high_cpu_hosts: [],
      high_mem_hosts: [],
      top_event_types_24h: [],
    })
    expect(s.vcenter_count).toBe(0)
    expect(s.top_notable_events).toEqual([])
  })
})
