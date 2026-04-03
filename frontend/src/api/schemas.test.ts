import { describe, expect, it } from 'vitest'
import {
  eventRowSchema,
  normalizeEventListPayload,
  parseDigestListResponse,
  parseSummary,
} from './schemas'

describe('eventRowSchema', () => {
  it('parses API event row shape (e.g. PATCH response)', () => {
    const row = eventRowSchema.parse({
      id: 1,
      vcenter_id: 'vc',
      occurred_at: '2025-01-01T00:00:00Z',
      event_type: 't',
      message: 'm',
      severity: null,
      notable_score: 0,
      notable_tags: null,
      user_comment: 'hello',
    })
    expect(row.user_comment).toBe('hello')
  })
})

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

describe('parseDigestListResponse', () => {
  it('parses digest list envelope', () => {
    const raw = {
      items: [
        {
          id: 1,
          period_start: '2026-03-27T00:00:00Z',
          period_end: '2026-03-28T00:00:00Z',
          kind: 'daily',
          body_markdown: '# Hello',
          status: 'ok',
          error_message: null,
          llm_model: 'x',
          created_at: '2026-03-28T01:00:00Z',
        },
      ],
      total: 1,
    }
    const parsed = parseDigestListResponse(raw)
    expect(parsed.total).toBe(1)
    expect(parsed.items[0]?.body_markdown).toBe('# Hello')
    expect(parsed.items[0]?.id).toBe(1)
  })

  it('parses empty items with total', () => {
    const parsed = parseDigestListResponse({ items: [], total: 0 })
    expect(parsed.items).toEqual([])
    expect(parsed.total).toBe(0)
  })

  it('rejects invalid envelope', () => {
    expect(() => parseDigestListResponse({})).toThrow()
  })
})

describe('parseSummary', () => {
  it('parses dashboard summary payload', () => {
    const s = parseSummary({
      vcenter_count: 0,
      events_last_24h: 0,
      notable_events_last_24h: 0,
      top_notable_events: [],
      high_cpu_hosts: [
        {
          vcenter_id: '00000000-0000-0000-0000-000000000001',
          vcenter_label: 'vc-display',
          entity_name: 'esxi-1',
          entity_moid: 'moid-1',
          value: 90,
          sampled_at: '2026-01-01T00:00:00Z',
        },
      ],
      high_mem_hosts: [],
      top_event_types_24h: [],
    })
    expect(s.vcenter_count).toBe(0)
    expect(s.top_notable_events).toEqual([])
    expect(s.high_cpu_hosts[0]?.vcenter_label).toBe('vc-display')
  })
})
