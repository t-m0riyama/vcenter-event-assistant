import { useCallback, useEffect, useMemo, useState } from 'react'

import { apiGet, apiPost } from '../api'
import { buildIncidentTimelineBuildRequestPayload } from '../api/buildIncidentTimelineBuildRequestPayload'
import {
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotCreateResponseSchema,
  incidentTimelineManualSnapshotListResponseSchema,
  parseIncidentTimelineResponse,
  type IncidentTimelineManualSnapshotListItem,
  type IncidentTimeline,
  type VCenter,
} from '../api/schemas'
import { resolveEventApiRange } from '../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'
import { useTimeZone } from '../datetime/useTimeZone'
import { buildSnapshotMarkersForTimeline } from '../panels/timeline/timelineSnapshotMarkers'
import {
  ALERT_TOP_N_STORAGE_KEY,
  getInitialAlertTopN,
  parseAlertTopN,
} from '../panels/timeline/timelineAlertTopNStorage'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'
import { usePeriodMetricThresholdFields } from './usePeriodMetricThresholdFields'

const TIMELINE_SORT_ORDER_STORAGE_KEY = 'vea.timeline.sort_order'
type TimelineSortOrder = 'asc' | 'desc'

/**
 * タイムラインタブの生成・スナップショット・フィルタ状態をまとめる。
 */
export function useTimelinePanelController(onError: (e: string | null) => void) {
  const { timeZone } = useTimeZone()
  const thresholdFields = usePeriodMetricThresholdFields()

  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(METRICS_DEFAULT_ROLLING_DURATION_MS, 'UTC'),
  )
  const [vcenterId, setVcenterId] = useState<string>('')
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [timeline, setTimeline] = useState<IncidentTimeline | null>(null)
  const [loading, setLoading] = useState(false)
  const [savingSnapshot, setSavingSnapshot] = useState(false)
  const [operatorNote, setOperatorNote] = useState('')
  const [manualSnapshotAuditItems, setManualSnapshotAuditItems] = useState<
    IncidentTimelineManualSnapshotListItem[]
  >([])
  const [selectedManualSnapshotId, setSelectedManualSnapshotId] = useState<string | null>(null)
  const [includePeriodMetricsCpu, setIncludePeriodMetricsCpu] = useState(false)
  const [includePeriodMetricsMemory, setIncludePeriodMetricsMemory] = useState(false)
  const [includePeriodMetricsDiskIo, setIncludePeriodMetricsDiskIo] = useState(false)
  const [includePeriodMetricsNetworkIo, setIncludePeriodMetricsNetworkIo] = useState(false)
  const [alertTopN, setAlertTopN] = useState(getInitialAlertTopN)
  const [alertTopNInput, setAlertTopNInput] = useState(() => String(getInitialAlertTopN()))
  const [sortOrder, setSortOrder] = useState<TimelineSortOrder>(() => {
    if (typeof localStorage === 'undefined') {
      return 'desc'
    }
    const raw = localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY)
    return raw === 'asc' ? 'asc' : 'desc'
  })

  const snapshotMarkers = useMemo(
    () => buildSnapshotMarkersForTimeline(timeline, manualSnapshotAuditItems),
    [timeline, manualSnapshotAuditItems],
  )

  const fetchManualSnapshotAuditItems = useCallback(async () => {
    const listRaw = await apiGet<unknown>('/api/incident-timeline/snapshots/manual?limit=20&offset=0')
    const list = incidentTimelineManualSnapshotListResponseSchema.parse(listRaw)
    setManualSnapshotAuditItems(list.items)
    setSelectedManualSnapshotId((current) => {
      if (list.items.length === 0) {
        return null
      }
      if (current && list.items.some((item) => item.snapshot_id === current)) {
        return current
      }
      return list.items[0]?.snapshot_id ?? null
    })
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        await fetchManualSnapshotAuditItems()
      } catch (e) {
        onError(toErrorMessage(e))
      }
    })()
  }, [fetchManualSnapshotAuditItems, onError])

  useEffect(() => {
    if (typeof localStorage === 'undefined') {
      return
    }
    localStorage.setItem(TIMELINE_SORT_ORDER_STORAGE_KEY, sortOrder)
  }, [sortOrder])

  useEffect(() => {
    if (typeof localStorage === 'undefined') {
      return
    }
    localStorage.setItem(ALERT_TOP_N_STORAGE_KEY, String(alertTopN))
  }, [alertTopN])

  useEffect(() => {
    void (async () => {
      try {
        const raw = await apiGet<unknown>('/api/vcenters')
        setVcenters(asArray<VCenter>(raw))
      } catch (e) {
        onError(toErrorMessage(e))
      }
    })()
  }, [onError])

  const handleAlertTopNInputChange = useCallback((rawValue: string) => {
    setAlertTopNInput(rawValue)
    if (rawValue.trim() === '') {
      return
    }
    const parsed = parseAlertTopN(rawValue)
    if (parsed == null) {
      return
    }
    setAlertTopN(parsed)
  }, [])

  const buildTimelineOptions = useCallback(
    () => ({
      vcenterId,
      includePeriodMetricsCpu,
      includePeriodMetricsMemory,
      includePeriodMetricsDiskIo,
      includePeriodMetricsNetworkIo,
      metricThresholdCpuPct: thresholdFields.metricThresholdCpuPct,
      metricThresholdMemoryPct: thresholdFields.metricThresholdMemoryPct,
      metricThresholdDiskPct: thresholdFields.metricThresholdDiskPct,
      metricThresholdNetworkPct: thresholdFields.metricThresholdNetworkPct,
      alertTopN,
    }),
    [
      vcenterId,
      includePeriodMetricsCpu,
      includePeriodMetricsMemory,
      includePeriodMetricsDiskIo,
      includePeriodMetricsNetworkIo,
      thresholdFields.metricThresholdCpuPct,
      thresholdFields.metricThresholdMemoryPct,
      thresholdFields.metricThresholdDiskPct,
      thresholdFields.metricThresholdNetworkPct,
      alertTopN,
    ],
  )

  const resolveCurrentRange = useCallback(() => {
    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      return { ok: false as const, message: resolved.message }
    }
    if (!resolved.from || !resolved.to) {
      return { ok: false as const, message: '期間の開始と終了を指定してください。' }
    }
    return { ok: true as const, from: resolved.from, to: resolved.to }
  }, [rangeParts, timeZone])

  const generateTimeline = useCallback(async () => {
    const resolved = resolveCurrentRange()
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    onError(null)
    setLoading(true)
    try {
      const payload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: { from: resolved.from, to: resolved.to },
        options: buildTimelineOptions(),
      })
      const raw = await apiPost<unknown>('/api/incident-timeline', payload)
      const out = parseIncidentTimelineResponse(raw)
      setTimeline(out)
      await fetchManualSnapshotAuditItems()
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [resolveCurrentRange, onError, buildTimelineOptions, fetchManualSnapshotAuditItems])

  const loadTimelineFromSnapshot = useCallback(async (snapshot: IncidentTimelineManualSnapshotListItem) => {
    onError(null)
    setLoading(true)
    try {
      const raw = await apiPost<unknown>('/api/incident-timeline', snapshot.build_request_payload)
      const out = parseIncidentTimelineResponse(raw)
      setTimeline(out)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [onError])

  const saveManualSnapshot = useCallback(async () => {
    if (operatorNote.trim() === '') {
      return
    }
    const resolved = resolveCurrentRange()
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    onError(null)
    setSavingSnapshot(true)
    try {
      const buildRequestPayload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: { from: resolved.from, to: resolved.to },
        options: buildTimelineOptions(),
      })
      const tsIso = new Date().toISOString()
      const graphContext = {
        marker_timestamp_utc: tsIso,
        ...(vcenterId.trim() !== '' ? { vcenter_id: vcenterId } : {}),
        captured_range: { from: resolved.from, to: resolved.to },
      }
      const payload = incidentTimelineManualSnapshotCreateRequestSchema.parse({
        from: resolved.from,
        to: resolved.to,
        timestamp_utc: tsIso,
        operator_note: operatorNote.trim(),
        build_request_payload: buildRequestPayload,
        graph_context: graphContext,
      })
      const raw = await apiPost<unknown>('/api/incident-timeline/snapshots/manual', payload)
      incidentTimelineManualSnapshotCreateResponseSchema.parse(raw)
      await fetchManualSnapshotAuditItems()
      setOperatorNote('')
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setSavingSnapshot(false)
    }
  }, [
    operatorNote,
    resolveCurrentRange,
    onError,
    buildTimelineOptions,
    vcenterId,
    fetchManualSnapshotAuditItems,
  ])

  const handleAlertTopNBlur = useCallback(() => {
    setAlertTopNInput(String(alertTopN))
  }, [alertTopN])

  return {
    rangeParts,
    setRangeParts,
    vcenters,
    vcenterId,
    setVcenterId,
    timeline,
    loading,
    savingSnapshot,
    operatorNote,
    setOperatorNote,
    manualSnapshotAuditItems,
    selectedManualSnapshotId,
    setSelectedManualSnapshotId,
    includePeriodMetricsCpu,
    setIncludePeriodMetricsCpu,
    includePeriodMetricsMemory,
    setIncludePeriodMetricsMemory,
    includePeriodMetricsDiskIo,
    setIncludePeriodMetricsDiskIo,
    includePeriodMetricsNetworkIo,
    setIncludePeriodMetricsNetworkIo,
    alertTopNInput,
    alertTopN,
    setAlertTopNInput,
    setAlertTopN,
    sortOrder,
    setSortOrder,
    snapshotMarkers,
    ...thresholdFields,
    handleAlertTopNInputChange,
    handleAlertTopNBlur,
    generateTimeline,
    loadTimelineFromSnapshot,
    saveManualSnapshot,
  }
}
