import { describe, expect, it } from 'vitest'

import {
  incidentTimelineManualSnapshotListItemSchema,
  type IncidentTimelineManualSnapshotListItem,
} from '../api/schemas'
import { resolveMetricsReplay } from './metricsReplay'

const VCENTER_ID = '11111111-1111-4111-8111-111111111111'

/** 外側の期間（from / to）と build_request_payload の期間はわざとずらす。どちらに戻ったかを区別するため。 */
const RAW_LIST_ITEM = {
  snapshot_id: 's1',
  from: '2026-03-21T00:00:00Z',
  to: '2026-03-21T06:00:00Z',
  operator_note: 'm',
  timestamp_utc: '2026-03-22T03:00:00Z',
  build_request_payload: { from: '2026-03-22T00:00:00Z', to: '2026-03-22T02:00:00Z', vcenter_id: VCENTER_ID },
  snapshot_kind: 'manual',
  has_result: false,
}

/** graph_context が無いときに戻る値。 */
const FALLBACK = {
  kind: 'snapshot',
  from: '2026-03-22T00:00:00Z',
  to: '2026-03-22T02:00:00Z',
  vcenterId: VCENTER_ID,
  metricKey: '',
  chartEventType: '',
  markerUtc: '2026-03-22T03:00:00Z',
}

function snapshotItem(
  graph_context: IncidentTimelineManualSnapshotListItem['graph_context'],
): IncidentTimelineManualSnapshotListItem {
  return incidentTimelineManualSnapshotListItemSchema.parse({ ...RAW_LIST_ITEM, graph_context })
}

describe('resolveMetricsReplay（スナップショット）', () => {
  it('graph_context の値を使う', () => {
    const replay = resolveMetricsReplay({
      item: snapshotItem({
        metric_key: 'host.cpu.usage_pct',
        chart_event_type: 'VmPoweredOffEvent',
        marker_timestamp_utc: '2026-03-22T01:00:00Z',
        vcenter_id: '22222222-2222-4222-8222-222222222222',
        captured_range: { from: '2026-03-21T23:00:00Z', to: '2026-03-22T03:00:00Z' },
      }),
      nonce: 1,
    })
    expect(replay).toMatchObject({
      kind: 'snapshot',
      from: '2026-03-21T23:00:00Z',
      to: '2026-03-22T03:00:00Z',
      vcenterId: '22222222-2222-4222-8222-222222222222',
      metricKey: 'host.cpu.usage_pct',
      chartEventType: 'VmPoweredOffEvent',
      markerUtc: '2026-03-22T01:00:00Z',
    })
  })

  it('graph_context が null なら、build_request_payload の期間と vCenter、timestamp_utc の時刻に戻り、指標と種別は空になる', () => {
    expect(resolveMetricsReplay({ item: snapshotItem(null), nonce: 1 })).toMatchObject(FALLBACK)
  })

  // 一覧のスキーマが読めない graph_context を null にした項目も、同じ値で開ける（Issue #332）。
  it('読めない graph_context を持つ一覧の項目も、graph_context が無いものとして開く', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse({
      ...RAW_LIST_ITEM,
      graph_context: {
        metric_key: 'host.cpu.usage_pct',
        marker_timestamp_utc: '2026-03-22T10:00:00+09:00',
        captured_range: { from: '2026-03-21T23:00:00Z', to: '2026-03-22T03:00:00Z' },
      },
    })
    expect(resolveMetricsReplay({ item, nonce: 1 })).toMatchObject(FALLBACK)
  })
})
