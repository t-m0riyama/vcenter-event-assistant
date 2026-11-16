import { describe, expect, it } from 'vitest'

import { VIEW_RESPONSE_EXAMPLE } from '../../test/timelineViewFixtures'
import { incidentTimelineViewResponseSchema } from './incidentTimelineView'

describe('incidentTimelineViewResponseSchema', () => {
  it('API の応答例を受け付け、Z の無い時刻もそのまま保つ', () => {
    const parsed = incidentTimelineViewResponseSchema.parse(VIEW_RESPONSE_EXAMPLE)
    expect(parsed.items).toHaveLength(2)
    expect(parsed.items[0].timestamp_utc).toBe('2026-03-22T00:10:00')
    expect(parsed.items[1].detail).toBeUndefined()
  })

  it('任意の項目が欠けていても受け付ける（旧サーバや None の省略）', () => {
    const parsed = incidentTimelineViewResponseSchema.parse({
      ...VIEW_RESPONSE_EXAMPLE,
      anchor_utc: undefined,
      items: [{ id: 'log:1', kind: 'log', timestamp_utc: '2026-03-22T00:01:00Z', level: 'error', title: 't' }],
      highlights: {},
    })
    expect(parsed.items[0].count).toBe(1)
    expect(parsed.highlights.top_entities).toEqual([])
  })

  it('未知のレベルは拒否する', () => {
    expect(() =>
      incidentTimelineViewResponseSchema.parse({
        ...VIEW_RESPONSE_EXAMPLE,
        items: [{ ...VIEW_RESPONSE_EXAMPLE.items[0], level: 'fatal' }],
      }),
    ).toThrow()
  })
})
