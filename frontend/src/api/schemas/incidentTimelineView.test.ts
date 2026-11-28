import { describe, expect, it } from 'vitest'

import { VIEW_RESPONSE_EXAMPLE } from '../../test/timelineViewFixtures'
import { eventPatternsResponseSchema } from './eventPatterns'
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
    expect(parsed.config_change_items_shown).toBe(0)
    expect(parsed.highlights.top_entities).toEqual([])
    expect(parsed.highlights.detected_patterns).toEqual([])
    expect(parsed.highlights.detected_patterns_total).toBe(0)
    expect(parsed.highlights.omitted_patterns).toEqual([])
    expect(parsed.highlights).toMatchObject({
      new_log_patterns: null,
      new_log_patterns_total: 0,
      log_patterns_backfill_pending: false,
      log_patterns_warming_up: [],
      log_patterns_warming_up_total: 0,
      new_log_patterns_out_of_retention: false,
    })
  })

  it('未知のレベルは拒否する', () => {
    expect(() =>
      incidentTimelineViewResponseSchema.parse({
        ...VIEW_RESPONSE_EXAMPLE,
        items: [{ ...VIEW_RESPONSE_EXAMPLE.items[0], level: 'fatal' }],
      }),
    ).toThrow()
  })

  it('保存済みの検知でデバイス項目を省略しても読める', () => {
    const parsed = incidentTimelineViewResponseSchema.parse({
      ...VIEW_RESPONSE_EXAMPLE,
      highlights: {
        detected_patterns: [{
          pattern_id: 'apd-timeout',
          title: 'APD のタイムアウト',
          description: '',
          level: 'critical',
          vcenter_id: 'vc-1',
          entity_moid: 'host-1',
          first_utc: '2026-03-22T00:00:00Z',
          last_utc: '2026-03-22T00:00:00Z',
          event_count: 1,
          event_ids: [1],
        }],
      },
    })
    expect(parsed.highlights.detected_patterns[0]).toMatchObject({ subject: null, device_id: null })
  })

  it('パターン一覧でデバイスの発生を読める', () => {
    const [pattern] = eventPatternsResponseSchema.parse([{
      id: 'pdl',
      title: 'PDL',
      description: '',
      level: 'critical',
      kind: 'occurrence',
      steps: [{ event_types: ['esx.problem.scsi.device.state.permanentloss'] }],
      within_minutes: 5,
      min_count: null,
      subject: 'device',
    }])
    expect(pattern).toMatchObject({ kind: 'occurrence', subject: 'device' })
  })
})
