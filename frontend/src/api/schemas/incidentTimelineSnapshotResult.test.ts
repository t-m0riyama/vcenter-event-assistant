import { describe, expect, it } from 'vitest'

import {
  incidentTimelineBuildRequestSchema,
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotCreateResponseSchema,
  incidentTimelineManualSnapshotListResponseSchema,
  incidentTimelineManualSnapshotDetailSchema,
  incidentTimelineManualSnapshotListItemSchema,
} from '.'
import { emptyViewResponse, VIEW_RESPONSE_EXAMPLE } from '../../test/timelineViewFixtures'

const base = {
  snapshot_id: 's1',
  from: '2026-03-10T00:00:00Z',
  to: '2026-03-10T03:00:00Z',
  operator_note: 'memo',
  timestamp_utc: '2026-03-10T03:30:00Z',
  build_request_payload: { from: '2026-03-10T00:00:00Z', to: '2026-03-10T03:00:00Z' },
}

describe('スナップショットの結果保存のスキーマ', () => {
  it('旧データの一覧項目は has_result が false、view_request が無い', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse(base)
    expect(item.has_result).toBe(false)
    expect(item.view_request ?? null).toBeNull()
  })

  it('読めない形の view_request は null として扱い、一覧全体を壊さない', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse({ ...base, has_result: true, view_request: { x: 1 } })
    expect(item.view_request).toBeNull()
  })

  it('詳細は結果を持ち、読めない形の結果は null になる', () => {
    const ok = incidentTimelineManualSnapshotDetailSchema.parse({ ...base, has_result: true, result: emptyViewResponse() })
    expect(ok.result?.total_items).toBe(0)
    const drifted = incidentTimelineManualSnapshotDetailSchema.parse({ ...base, has_result: true, result: { legacy: 1 } })
    expect(drifted.result).toBeNull()
  })

  it('構成変更の項目が無い保存済みの結果を既定値で読む', () => {
    const detail = incidentTimelineManualSnapshotDetailSchema.parse({
      ...base, has_result: true, result: VIEW_RESPONSE_EXAMPLE,
    })
    expect(detail.result).toMatchObject({
      config_change_items_total: 0,
      config_change_items_shown: 0,
      config_change_items_truncated: false,
      highlights: { config_changes_total: 0, config_change_counts: {}, config_changes_truncated: false },
    })
    expect(detail.result?.highlights).not.toHaveProperty('config_changes')
    expect(detail.result?.items[0]).not.toHaveProperty('config_change_kind')
  })

  it('保存のリクエストは view_request を持てるが、結果は送れない', () => {
    const body = { from: base.from, to: base.to, timestamp_utc: base.timestamp_utc, operator_note: 'm' }
    expect(
      incidentTimelineManualSnapshotCreateRequestSchema.parse({ ...body, view_request: { from: base.from, to: base.to } })
        .view_request,
    ).toEqual({ from: base.from, to: base.to })
    expect(() => incidentTimelineManualSnapshotCreateRequestSchema.parse({ ...body, result: {} })).toThrow()
  })
})

/** バックエンドが実際に返す形（None は null で返る）。`tests/test_incident_timeline_snapshot_result.py` の実応答から写した。 */
const ACTUAL_GRAPH_CONTEXT = {
  metric_key: null,
  chart_event_type: null,
  marker_timestamp_utc: '2026-03-22T03:00:00Z',
  vcenter_id: null,
  captured_range: { from: '2026-03-22T00:00:00Z', to: '2026-03-22T02:00:00Z' },
}
const ACTUAL_BUILD_REQUEST = {
  from: '2026-03-22T00:00:00Z',
  to: '2026-03-22T02:00:00Z',
  vcenter_id: null,
  top_notable_min_score: 1,
  alert_top_n: 3,
  include_period_metrics_cpu: false,
  include_period_metrics_memory: false,
  include_period_metrics_disk_io: false,
  include_period_metrics_network_io: false,
  metric_threshold_cpu_pct: null,
  metric_threshold_memory_pct: null,
  metric_threshold_disk_pct: null,
  metric_threshold_network_pct: null,
}
const ACTUAL_VIEW_REQUEST = {
  from: '2026-03-22T00:00:00Z',
  to: '2026-03-22T02:00:00Z',
  vcenter_id: null,
  entity: null,
  anchor: null,
  min_score: 1,
  sources: ['event', 'alert', 'metric', 'log'],
  metric_threshold_cpu_pct: 80.0,
  metric_threshold_memory_pct: 85.0,
  metric_threshold_disk_pct: 75.0,
  metric_threshold_network_pct: 75.0,
  item_limit: 500,
}
const ACTUAL_LIST_ITEM = {
  snapshot_id: 'ef25d69a-f85c-419b-9fec-b98354eca459',
  from: '2026-03-22T00:00:00Z',
  to: '2026-03-22T02:00:00Z',
  operator_note: 'm',
  timestamp_utc: '2026-03-22T03:00:00Z',
  build_request_payload: ACTUAL_BUILD_REQUEST,
  snapshot_kind: 'manual',
  trigger_id: null,
  trigger_evidence: null,
  graph_context: ACTUAL_GRAPH_CONTEXT,
  has_result: true,
  view_request: ACTUAL_VIEW_REQUEST,
  created_at: '2026-11-16T08:12:30.143246Z',
}

describe('バックエンドの実際の応答の形（null を含む）', () => {
  it('一覧: graph_context の metric_key / chart_event_type が null でも読め、未指定として扱う', () => {
    const parsed = incidentTimelineManualSnapshotListResponseSchema.parse({
      items: [ACTUAL_LIST_ITEM],
      total: 1,
      limit: 20,
      offset: 0,
    })
    const gc = parsed.items[0].graph_context
    expect(gc?.metric_key).toBeUndefined()
    expect(gc?.chart_event_type).toBeUndefined()
    expect(gc?.captured_range).toEqual({ from: '2026-03-22T00:00:00Z', to: '2026-03-22T02:00:00Z' })
    expect(parsed.items[0].view_request?.min_score).toBe(1)
  })

  it('作成の応答・詳細も読める', () => {
    const createLike: Record<string, unknown> = { ...ACTUAL_LIST_ITEM }
    for (const key of ['has_result', 'view_request', 'trigger_evidence', 'from', 'to']) delete createLike[key]
    expect(incidentTimelineManualSnapshotCreateResponseSchema.parse(createLike).graph_context?.metric_key).toBeUndefined()
    const detail = incidentTimelineManualSnapshotDetailSchema.parse({ ...ACTUAL_LIST_ITEM, result: emptyViewResponse() })
    expect(detail.result).not.toBeNull()
    expect(detail.graph_context?.chart_event_type).toBeUndefined()
  })

  it('graph_context の他の項目や view_request の項目が null でも拒否しない', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse({
      ...ACTUAL_LIST_ITEM,
      graph_context: { ...ACTUAL_GRAPH_CONTEXT, marker_timestamp_utc: null, captured_range: null },
      view_request: { ...ACTUAL_VIEW_REQUEST, min_score: null, sources: null, item_limit: null, metric_threshold_cpu_pct: null },
    })
    expect(item.view_request).not.toBeNull()
    expect(item.graph_context?.marker_timestamp_utc).toBeUndefined()
  })

  it('保存のリクエストに送る graph_context は null を含まない形のまま通る', () => {
    const body = { from: ACTUAL_LIST_ITEM.from, to: ACTUAL_LIST_ITEM.to, timestamp_utc: '2026-03-22T03:00:00Z', operator_note: 'm' }
    const parsed = incidentTimelineManualSnapshotCreateRequestSchema.parse({
      ...body,
      graph_context: { marker_timestamp_utc: '2026-03-22T03:00:00Z' },
    })
    expect(JSON.stringify(parsed.graph_context)).not.toContain('metric_key')
  })
})

/**
 * 画面では読めない graph_context（Issue #332）。
 * 日時は PR #339 より前のサーバが送られた形のまま保存して返していた。
 * vcenter_id は今のサーバ（Python の uuid.UUID）も受け付けるが、zod の uuid() は RFC 4122 の形でないと拒否する。
 */
const UNREADABLE_GRAPH_CONTEXTS: Record<string, Record<string, unknown>> = {
  'marker_timestamp_utc が +09:00': { ...ACTUAL_GRAPH_CONTEXT, marker_timestamp_utc: '2026-01-01T09:30:00+09:00' },
  'captured_range.from にタイムゾーンが無い': {
    ...ACTUAL_GRAPH_CONTEXT,
    captured_range: { from: '2026-03-22T00:00:00', to: '2026-03-22T02:00:00Z' },
  },
  'vcenter_id が RFC 4122 の形でない': { ...ACTUAL_GRAPH_CONTEXT, vcenter_id: '11111111-1111-1111-1111-111111111111' },
}
const UNREADABLE_GRAPH_CONTEXT = UNREADABLE_GRAPH_CONTEXTS['marker_timestamp_utc が +09:00']

describe('読めない graph_context（Issue #332）', () => {
  it.each(Object.entries(UNREADABLE_GRAPH_CONTEXTS))('一覧の項目は graph_context を null として読む（%s）',(_, graph_context) => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse({ ...ACTUAL_LIST_ITEM, graph_context })
    expect(item.graph_context).toBeNull()
  })

  it('読めない項目が 1 件あっても一覧全体は読め、他の項目の graph_context は残る', () => {
    const parsed = incidentTimelineManualSnapshotListResponseSchema.parse({
      items: [
        { ...ACTUAL_LIST_ITEM, snapshot_id: 'bad', graph_context: UNREADABLE_GRAPH_CONTEXT },
        { ...ACTUAL_LIST_ITEM, snapshot_id: 'good' },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    })
    expect(parsed.items.map((item) => item.snapshot_id)).toEqual(['bad', 'good'])
    expect(parsed.items[0].graph_context).toBeNull()
    expect(parsed.items[1].graph_context?.marker_timestamp_utc).toBe('2026-03-22T03:00:00Z')
  })

  it('詳細と保存の応答も graph_context を null として読む', () => {
    const graph_context = UNREADABLE_GRAPH_CONTEXT
    const detail = incidentTimelineManualSnapshotDetailSchema.parse({ ...ACTUAL_LIST_ITEM, graph_context })
    expect(detail.graph_context).toBeNull()
    const createLike: Record<string, unknown> = { ...ACTUAL_LIST_ITEM, graph_context }
    for (const key of ['has_result', 'view_request', 'trigger_evidence', 'from', 'to']) delete createLike[key]
    expect(incidentTimelineManualSnapshotCreateResponseSchema.parse(createLike).graph_context).toBeNull()
  })

  it('保存の要求は、読めない graph_context を黙って捨てずに拒否する', () => {
    const body = { from: ACTUAL_LIST_ITEM.from, to: ACTUAL_LIST_ITEM.to, timestamp_utc: '2026-03-22T03:00:00Z', operator_note: 'm' }
    expect(() =>
      incidentTimelineManualSnapshotCreateRequestSchema.parse({
        ...body,
        graph_context: { marker_timestamp_utc: '2026-01-01T09:30:00+09:00' },
      }),
    ).toThrow()
  })
})

describe('保存済み build_request_payload の vcenter_id（Issue #341）', () => {
  const legacyId = '11111111-1111-1111-1111-111111111111'
  const regularId = 'ef25d69a-f85c-419b-9fec-b98354eca459'
  const payload = { ...ACTUAL_BUILD_REQUEST, vcenter_id: legacyId }

  it('通常の UUID と RFC 形式以外の UUID が混在する一覧を読み、全項目を保持する', () => {
    const regularPayload = { ...ACTUAL_BUILD_REQUEST, vcenter_id: regularId }
    const parsed = incidentTimelineManualSnapshotListResponseSchema.parse({
      items: [
        { ...ACTUAL_LIST_ITEM, build_request_payload: regularPayload },
        { ...ACTUAL_LIST_ITEM, snapshot_id: 'legacy', build_request_payload: payload },
      ],
      total: 2, limit: 20, offset: 0,
    })
    expect(parsed.items.map((item) => item.build_request_payload)).toEqual([regularPayload, payload])
  })

  it('保存の応答と詳細も build_request_payload 全体を保持する', () => {
    const response = { ...ACTUAL_LIST_ITEM, build_request_payload: payload }
    expect(incidentTimelineManualSnapshotCreateResponseSchema.parse(response).build_request_payload).toEqual(payload)
    expect(incidentTimelineManualSnapshotDetailSchema.parse(response).build_request_payload).toEqual(payload)
  })

  it('null と省略を受け付け、不正な ID は拒否する', () => {
    for (const build_request_payload of [ACTUAL_BUILD_REQUEST, base.build_request_payload]) {
      expect(incidentTimelineManualSnapshotListItemSchema.parse({ ...ACTUAL_LIST_ITEM, build_request_payload }).build_request_payload)
        .toEqual(build_request_payload)
    }
    expect(() => incidentTimelineManualSnapshotListItemSchema.parse({
      ...ACTUAL_LIST_ITEM, build_request_payload: { ...payload, vcenter_id: 'not-a-uuid' },
    })).toThrow()
  })

  it('保存の要求では RFC 形式以外の UUID を拒否する', () => {
    expect(() => incidentTimelineBuildRequestSchema.parse(payload)).toThrow()
    expect(() => incidentTimelineManualSnapshotCreateRequestSchema.parse({
      from: base.from, to: base.to, timestamp_utc: base.timestamp_utc, operator_note: 'm',
      build_request_payload: payload,
    })).toThrow()
  })
})
