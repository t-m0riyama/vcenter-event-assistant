import { useCallback, useState } from 'react'

import { apiGet, apiPost } from '../api'
import { buildIncidentTimelineBuildRequestPayload } from '../api/buildIncidentTimelineBuildRequestPayload'
import {
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotCreateResponseSchema,
  incidentTimelineManualSnapshotListResponseSchema,
  type IncidentTimelineManualSnapshotListItem,
} from '../api/schemas'
import type { ResolvedRange } from '../panels/timeline/timelineModel'
import { toErrorMessage } from '../utils/errors'
import {
  DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  DEFAULT_METRIC_THRESHOLD_DISK_PCT,
  DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
} from './periodMetricThresholdDefaults'

/** スナップショットから条件へ写す値。保存済みの期間と vCenter だけを使う。 */
export function snapshotConditions(item: IncidentTimelineManualSnapshotListItem): {
  range: ResolvedRange
  vcenterId: string
} {
  return {
    range: { from: new Date(item.from).toISOString(), to: new Date(item.to).toISOString() },
    vcenterId: item.graph_context?.vcenter_id ?? item.build_request_payload.vcenter_id ?? '',
  }
}

/**
 * 手動スナップショットの一覧・保存・選択。折りたたみを開いたときに一覧を読む。
 * 保存の API とデータ形式は旧タイムラインのまま（結果の保存は別の変更）。
 * 選んだときだけ条件へ反映する（先頭を自動で選ぶと、URL の条件を上書きしてしまうため）。
 */
export function useTimelineSnapshots(params: {
  onError: (e: string | null) => void
  /** 画面の vCenter 条件。保存の `graph_context` に入れる。 */
  vcenterId: string
  /** 表示中の結果を取得した期間。無ければ保存できない。 */
  loadedRange: ResolvedRange | null
  applyConditions: (range: ResolvedRange, vcenterId: string) => void
}) {
  const { onError, vcenterId, loadedRange, applyConditions } = params
  const [open, setOpenState] = useState(false)
  const [items, setItems] = useState<IncidentTimelineManualSnapshotListItem[]>([])
  const [listLoaded, setListLoaded] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [operatorNote, setOperatorNote] = useState('')
  const [saving, setSaving] = useState(false)

  const fetchItems = useCallback(async () => {
    try {
      const raw = await apiGet<unknown>('/api/incident-timeline/snapshots/manual?limit=20&offset=0')
      setItems(incidentTimelineManualSnapshotListResponseSchema.parse(raw).items)
      setListLoaded(true)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [onError])

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next)
      if (next && !listLoaded) void fetchItems()
    },
    [fetchItems, listLoaded],
  )

  const select = useCallback(
    (item: IncidentTimelineManualSnapshotListItem) => {
      setSelectedId(item.snapshot_id)
      const { range, vcenterId: id } = snapshotConditions(item)
      applyConditions(range, id)
    },
    [applyConditions],
  )

  const save = useCallback(async () => {
    const note = operatorNote.trim()
    if (note === '' || !loadedRange) return
    onError(null)
    setSaving(true)
    try {
      const buildRequestPayload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: loadedRange,
        options: {
          vcenterId,
          includePeriodMetricsCpu: false,
          includePeriodMetricsMemory: false,
          includePeriodMetricsDiskIo: false,
          includePeriodMetricsNetworkIo: false,
          metricThresholdCpuPct: DEFAULT_METRIC_THRESHOLD_CPU_PCT,
          metricThresholdMemoryPct: DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
          metricThresholdDiskPct: DEFAULT_METRIC_THRESHOLD_DISK_PCT,
          metricThresholdNetworkPct: DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
        },
      })
      const tsIso = new Date().toISOString()
      const payload = incidentTimelineManualSnapshotCreateRequestSchema.parse({
        from: loadedRange.from,
        to: loadedRange.to,
        timestamp_utc: tsIso,
        operator_note: note,
        build_request_payload: buildRequestPayload,
        graph_context: {
          marker_timestamp_utc: tsIso,
          ...(vcenterId.trim() !== '' ? { vcenter_id: vcenterId } : {}),
          captured_range: { from: loadedRange.from, to: loadedRange.to },
        },
      })
      const raw = await apiPost<unknown>('/api/incident-timeline/snapshots/manual', payload)
      incidentTimelineManualSnapshotCreateResponseSchema.parse(raw)
      await fetchItems()
      setOperatorNote('')
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }, [operatorNote, loadedRange, onError, vcenterId, fetchItems])

  return { open, setOpen, items, listLoaded, selectedId, select, operatorNote, setOperatorNote, saving, save }
}
