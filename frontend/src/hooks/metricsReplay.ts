import type { IncidentTimelineManualSnapshotListItem } from '../api/schemas'

/** グラフのタブに渡す「この期間・この vCenter を見たい」という条件。スナップショットに依存しない。 */
export type MetricsFocus = {
  /** 期間（UTC の ISO 8601）。 */
  from: string
  to: string
  vcenterId: string | null
  /** グラフに縦線で示す起点の時刻。 */
  markerUtc: string | null
  /** 指定すれば系列を選ぶ。無ければ先頭の系列を使う。 */
  metricKey?: string | null
  chartEventType?: string | null
}

/** メトリクスタブで一度だけ適用する条件。`nonce` が変わるたびに適用し直す。 */
export type MetricsSnapshotReplayInput = {
  item: IncidentTimelineManualSnapshotListItem
  nonce: number
}
export type MetricsFocusReplayInput = { focus: MetricsFocus; nonce: number }
export type MetricsReplayInput = MetricsSnapshotReplayInput | MetricsFocusReplayInput

export type ResolvedMetricsReplay = {
  /** 同じ条件かどうかの判定に使う元の参照（スナップショットまたは focus）。 */
  source: object
  nonce: number
  from: string
  to: string
  vcenterId: string
  metricKey: string
  chartEventType: string
  markerUtc: string
  /** 縦線に添える文言。 */
  markerLabel: string
}

/** スナップショットと focus を同じ形にそろえる。適用できない（nonce が 1 未満など）ときは null。 */
export function resolveMetricsReplay(input: MetricsReplayInput | null | undefined): ResolvedMetricsReplay | null {
  if (!input || input.nonce < 1) return null
  if ('item' in input) {
    const item = input.item
    const br = item.build_request_payload
    const gc = item.graph_context
    return {
      source: item,
      nonce: input.nonce,
      from: gc?.captured_range?.from ?? br.from,
      to: gc?.captured_range?.to ?? br.to,
      vcenterId: String(gc?.vcenter_id ?? br.vcenter_id ?? ''),
      metricKey: gc?.metric_key ?? '',
      chartEventType: gc?.chart_event_type ?? '',
      markerUtc: String(gc?.marker_timestamp_utc ?? item.timestamp_utc),
      markerLabel: 'スナップショット',
    }
  }
  const f = input.focus
  return {
    source: f,
    nonce: input.nonce,
    from: f.from,
    to: f.to,
    vcenterId: f.vcenterId ?? '',
    metricKey: f.metricKey ?? '',
    chartEventType: f.chartEventType ?? '',
    markerUtc: f.markerUtc ?? '',
    markerLabel: '起点',
  }
}
