import { describe, expect, it } from 'vitest'
import {
  eventRowSchema,
  normalizeEventListPayload,
  parseDigestListResponse,
  parseSummary,
  parseChatResponse,
  parseChatPreviewResponse,
  chatRequestSchema,
  incidentTimelineBuildRequestSchema,
  incidentTimelineManualSnapshotListItemSchema,
  parseIncidentTimelineResponse,
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

describe('parseChatPreviewResponse', () => {
  it('parses valid chat preview response', () => {
    const raw = {
      context_block: 'This is the context block',
      conversation: [
        { role: 'user', content: 'hello' }
      ],
      llm_context: {
        json_truncated: false,
        estimated_input_tokens: 10,
        max_input_tokens: 1000,
        message_turns: 1
      }
    }
    const parsed = parseChatPreviewResponse(raw)
    expect(parsed.context_block).toBe('This is the context block')
    expect(parsed.conversation[0]?.role).toBe('user')
    expect(parsed.llm_context?.estimated_input_tokens).toBe(10)
  })

  it('rejects invalid chat preview response without context block', () => {
    expect(() => parseChatPreviewResponse({ conversation: [] })).toThrow()
  })

  it('parses incident timeline in chat preview response', () => {
    const raw = {
      context_block: 'ctx',
      conversation: [{ role: 'user', content: 'hello' }],
      incident_timeline: {
        columns: [
          {
            timestamp_utc: '2026-05-07T00:00:00Z',
            bucket_start_utc: '2026-05-07T00:00:00Z',
            bucket_end_utc: '2026-05-07T01:00:00Z',
            items: [
              { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' },
              { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A1' },
            ],
            visible_items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A1' }],
            hidden_count: 1,
          },
        ],
      },
    }
    const parsed = parseChatPreviewResponse(raw)
    expect(parsed.incident_timeline?.columns).toHaveLength(1)
    expect(parsed.incident_timeline?.columns[0]?.hidden_count).toBe(1)
    expect(parsed.incident_timeline?.columns[0]?.bucket_start_utc).toBe('2026-05-07T00:00:00Z')
  })

  it('旧ペイロードで visible_items と hidden_count が無くても解釈できる', () => {
    const raw = {
      context_block: 'ctx',
      conversation: [{ role: 'user', content: 'hello' }],
      incident_timeline: {
        columns: [
          {
            timestamp_utc: '2026-05-07T00:00:00Z',
            items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' }],
          },
        ],
      },
    }
    const parsed = parseChatPreviewResponse(raw)
    expect(parsed.incident_timeline?.columns[0]?.visible_items).toEqual([
      { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' },
    ])
    expect(parsed.incident_timeline?.columns[0]?.hidden_count).toBe(0)
  })

  it('incident_timeline が null でも解釈できる', () => {
    const raw = {
      context_block: 'ctx',
      conversation: [{ role: 'user', content: 'hello' }],
      incident_timeline: null,
    }
    const parsed = parseChatPreviewResponse(raw)
    expect(parsed.incident_timeline).toBeNull()
  })
})

describe('parseChatResponse', () => {
  it('trigger_evidence オブジェクトを解釈して保持する', () => {
    const parsed = parseChatResponse({
      assistant_content: '回答',
      error: null,
      trigger_evidence: {
        trigger_type: 'alert_rule',
        summary: 'CPU閾値超過を検知',
        source_id: 'rule:cpu-over-80',
      },
    })
    expect(parsed.trigger_evidence?.trigger_type).toBe('alert_rule')
    expect(parsed.trigger_evidence?.summary).toBe('CPU閾値超過を検知')
    expect(parsed.trigger_evidence?.source_id).toBe('rule:cpu-over-80')
  })

  it('trigger_evidence が null でも解釈できる', () => {
    const parsed = parseChatResponse({
      assistant_content: '回答',
      error: null,
      trigger_evidence: null,
    })
    expect(parsed.trigger_evidence).toBeNull()
  })

  it('trigger_evidence が無くても後方互換で解釈できる', () => {
    const parsed = parseChatResponse({
      assistant_content: '回答',
      error: null,
    })
    expect(parsed.trigger_evidence).toBeUndefined()
  })

  it('trigger_evidence の型が不正なとき拒否する', () => {
    expect(() =>
      parseChatResponse({
        assistant_content: '回答',
        error: null,
        trigger_evidence: {
          trigger_type: 123,
          summary: 'CPU閾値超過を検知',
        },
      }),
    ).toThrow()
  })
})

describe('chatRequestSchema', () => {
  it('任意閾値4項目に 0〜100 を受け入れる', () => {
    const parsed = chatRequestSchema.parse({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      messages: [{ role: 'user', content: '状況を教えて' }],
      metric_threshold_cpu_pct: 80,
      metric_threshold_memory_pct: 75,
      metric_threshold_disk_pct: 70,
      metric_threshold_network_pct: 65,
    })
    expect(parsed.metric_threshold_cpu_pct).toBe(80)
    expect(parsed.metric_threshold_memory_pct).toBe(75)
    expect(parsed.metric_threshold_disk_pct).toBe(70)
    expect(parsed.metric_threshold_network_pct).toBe(65)
  })

  it('任意閾値4項目に null を受け入れる', () => {
    const parsed = chatRequestSchema.parse({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      messages: [{ role: 'user', content: '状況を教えて' }],
      metric_threshold_cpu_pct: null,
      metric_threshold_memory_pct: null,
      metric_threshold_disk_pct: null,
      metric_threshold_network_pct: null,
    })
    expect(parsed.metric_threshold_cpu_pct).toBeNull()
    expect(parsed.metric_threshold_memory_pct).toBeNull()
    expect(parsed.metric_threshold_disk_pct).toBeNull()
    expect(parsed.metric_threshold_network_pct).toBeNull()
  })

  it('任意閾値が 0 未満または 100 超のとき拒否する', () => {
    expect(() =>
      chatRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        messages: [{ role: 'user', content: '状況を教えて' }],
        metric_threshold_cpu_pct: -1,
      }),
    ).toThrow()
    expect(() =>
      chatRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        messages: [{ role: 'user', content: '状況を教えて' }],
        metric_threshold_network_pct: 101,
      }),
    ).toThrow()
  })

  it('from/to が ISO UTC 形式でないとき拒否する', () => {
    expect(() =>
      chatRequestSchema.parse({
        from: '2026-05-07 00:00:00',
        to: '2026-05-08T00:00:00Z',
        messages: [{ role: 'user', content: '状況を教えて' }],
      }),
    ).toThrow()
    expect(() =>
      chatRequestSchema.parse({
        from: '2026-05-07T00:00:00+09:00',
        to: '2026-05-08T00:00:00Z',
        messages: [{ role: 'user', content: '状況を教えて' }],
      }),
    ).toThrow()
  })
})

describe('parseIncidentTimelineResponse', () => {
  it('parses incident timeline response payload for /api/incident-timeline', () => {
    const parsed = parseIncidentTimelineResponse({
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' }],
          visible_items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' }],
          hidden_count: 0,
        },
      ],
    })
    expect(parsed.columns).toHaveLength(1)
    expect(parsed.columns[0]?.visible_items[0]?.kind).toBe('event')
  })

  it('timestamp_utc に +00:00 形式が含まれても解釈できる', () => {
    const parsed = parseIncidentTimelineResponse({
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00+00:00',
          bucket_start_utc: '2026-05-07T00:00:00+00:00',
          bucket_end_utc: '2026-05-07T01:00:00+00:00',
          items: [
            { timestamp_utc: '2026-05-07T00:00:00+00:00', kind: 'event', title: 'E1' },
          ],
        },
      ],
    })
    expect(parsed.columns[0]?.timestamp_utc).toBe('2026-05-07T00:00:00+00:00')
    expect(parsed.columns[0]?.items[0]?.timestamp_utc).toBe('2026-05-07T00:00:00+00:00')
  })

  it('旧レスポンスで visible_items と hidden_count がなくても補完する', () => {
    const parsed = parseIncidentTimelineResponse({
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' }],
        },
      ],
    })
    expect(parsed.columns[0]?.visible_items).toEqual([
      { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' },
    ])
    expect(parsed.columns[0]?.hidden_count).toBe(0)
  })

  it('bucket_start_utc と bucket_end_utc が null でも解釈できる', () => {
    const parsed = parseIncidentTimelineResponse({
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          bucket_start_utc: null,
          bucket_end_utc: null,
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E1' }],
        },
      ],
    })
    expect(parsed.columns[0]?.bucket_start_utc).toBeNull()
    expect(parsed.columns[0]?.bucket_end_utc).toBeNull()
  })

  it('timestamp_utc が不正な列を拒否する', () => {
    expect(() =>
      parseIncidentTimelineResponse({
        columns: [{ timestamp_utc: '2026-05-07 00:00:00', items: [] }],
      }),
    ).toThrow()
  })
})

describe('incidentTimelineBuildRequestSchema', () => {
  it('accepts timeline build payload without messages', () => {
    const parsed = incidentTimelineBuildRequestSchema.parse({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      top_notable_min_score: 1,
      include_period_metrics_cpu: true,
      include_period_metrics_memory: false,
      include_period_metrics_disk_io: false,
      include_period_metrics_network_io: true,
      metric_threshold_cpu_pct: 80,
      metric_threshold_memory_pct: null,
      metric_threshold_disk_pct: 70,
      metric_threshold_network_pct: null,
    })
    expect(parsed.from).toBe('2026-05-07T00:00:00Z')
    expect(parsed.metric_threshold_cpu_pct).toBe(80)
  })

  it('vcenter_id が null でも受理する（旧保存データ互換）', () => {
    const parsed = incidentTimelineBuildRequestSchema.parse({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      vcenter_id: null,
    })
    expect(parsed.vcenter_id).toBeNull()
  })

  it('rejects messages field for timeline build payload', () => {
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        messages: [{ role: 'user', content: 'should not be accepted' }],
      }),
    ).toThrow()
  })

  it('from/to が ISO UTC 形式でないとき拒否する', () => {
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07 00:00:00',
        to: '2026-05-08T00:00:00Z',
      }),
    ).toThrow()
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07T00:00:00+09:00',
        to: '2026-05-08T00:00:00Z',
      }),
    ).toThrow()
  })

  it('alert_top_n を 1〜20 の範囲で受理する', () => {
    const parsed = incidentTimelineBuildRequestSchema.parse({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      alert_top_n: 5,
    })
    expect(parsed.alert_top_n).toBe(5)
  })

  it('alert_top_n が 1 未満や 20 超のとき拒否する', () => {
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        alert_top_n: 0,
      }),
    ).toThrow()
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        alert_top_n: 21,
      }),
    ).toThrow()
  })

  it('alert_top_n が整数でないとき拒否する', () => {
    expect(() =>
      incidentTimelineBuildRequestSchema.parse({
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
        alert_top_n: 1.5,
      }),
    ).toThrow()
  })
})

describe('incidentTimelineManualSnapshotListItemSchema', () => {
  it('自動スナップショット項目の追加フィールドを受理する', () => {
    const parsed = incidentTimelineManualSnapshotListItemSchema.parse({
      snapshot_id: '00000000-0000-0000-0000-000000000001',
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      operator_note: '自動スナップショット: Critical burst',
      timestamp_utc: '2026-05-07T01:00:00Z',
      build_request_payload: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      snapshot_kind: 'auto',
      trigger_id: 'critical_burst',
      trigger_evidence: {
        trigger_id: 'critical_burst',
        summary: '自動トリガー: Critical burst',
      },
    })
    expect(parsed.snapshot_kind).toBe('auto')
    expect(parsed.trigger_id).toBe('critical_burst')
  })
})
