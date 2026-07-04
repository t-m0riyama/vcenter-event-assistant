import { useCallback, useEffect, useMemo, useState } from 'react'
import './TimelinePanel.css'

import { apiGet, apiPost } from '../../api'
import { buildIncidentTimelineBuildRequestPayload } from '../../api/buildIncidentTimelineBuildRequestPayload'
import {
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotCreateResponseSchema,
  incidentTimelineManualSnapshotListResponseSchema,
  parseIncidentTimelineResponse,
  type IncidentTimelineManualSnapshotListItem,
  type IncidentTimeline,
  type VCenter,
} from '../../api/schemas'
import { resolveEventApiRange } from '../../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../../datetime/zonedRangeParts'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import { asArray } from '../../utils/asArray'
import { TimelineFilters } from './TimelineFilters'
import { TimelineResults } from './TimelineResults'
import { TimelineSnapshotActions } from './TimelineSnapshotActions'

const DEFAULT_METRIC_THRESHOLD_CPU_PCT = 80
const DEFAULT_METRIC_THRESHOLD_MEMORY_PCT = 85
const DEFAULT_METRIC_THRESHOLD_DISK_PCT = 75
const DEFAULT_METRIC_THRESHOLD_NETWORK_PCT = 75
const DEFAULT_ALERT_TOP_N = 7
const TIMELINE_SORT_ORDER_STORAGE_KEY = 'vea.timeline.sort_order'
const ALERT_TOP_N_STORAGE_KEY = 'vea.timeline.alert_top_n'
type TimelineSortOrder = 'asc' | 'desc'

function buildSnapshotMarkersForTimeline(
  timeline: IncidentTimeline | null,
  items: IncidentTimelineManualSnapshotListItem[],
): { timestamp_utc: string; label: string }[] {
  if (!timeline?.columns.length) {
    return []
  }
  const times = timeline.columns.map((c) => new Date(c.timestamp_utc).getTime())
  const minT = Math.min(...times)
  const maxT = Math.max(...times)
  const out: { timestamp_utc: string; label: string }[] = []
  for (const item of items) {
    const t = new Date(item.timestamp_utc).getTime()
    if (!Number.isFinite(t)) {
      continue
    }
    if (t >= minT && t <= maxT) {
      out.push({ timestamp_utc: item.timestamp_utc, label: item.operator_note })
    }
  }
  return out
}

function isValidMetricThresholdPercent(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 100
}

function parseAlertTopN(rawValue: string | null): number | null {
  if (rawValue == null || rawValue.trim() === '') {
    return null
  }
  const parsed = Number(rawValue)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
    return null
  }
  return parsed
}

function getInitialAlertTopN(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_ALERT_TOP_N
  }
  const parsed = parseAlertTopN(localStorage.getItem(ALERT_TOP_N_STORAGE_KEY))
  return parsed ?? DEFAULT_ALERT_TOP_N
}

export function TimelinePanel({
  onError,
  onOpenSnapshotInMetrics,
}: {
  onError: (e: string | null) => void
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
}) {
  const { timeZone } = useTimeZone()
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

  const [metricThresholdCpuPct, setMetricThresholdCpuPct] = useState(DEFAULT_METRIC_THRESHOLD_CPU_PCT)
  const [metricThresholdCpuInput, setMetricThresholdCpuInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_CPU_PCT),
  )
  const [metricThresholdMemoryPct, setMetricThresholdMemoryPct] = useState(
    DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  )
  const [metricThresholdMemoryInput, setMetricThresholdMemoryInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_MEMORY_PCT),
  )
  const [metricThresholdDiskPct, setMetricThresholdDiskPct] = useState(DEFAULT_METRIC_THRESHOLD_DISK_PCT)
  const [metricThresholdDiskInput, setMetricThresholdDiskInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_DISK_PCT),
  )
  const [metricThresholdNetworkPct, setMetricThresholdNetworkPct] = useState(
    DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
  )
  const [metricThresholdNetworkInput, setMetricThresholdNetworkInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_NETWORK_PCT),
  )
  const [alertTopN, setAlertTopN] = useState(getInitialAlertTopN)
  const [alertTopNInput, setAlertTopNInput] = useState(() => String(getInitialAlertTopN()))
  const snapshotMarkers = useMemo(
    () => buildSnapshotMarkersForTimeline(timeline, manualSnapshotAuditItems),
    [timeline, manualSnapshotAuditItems],
  )

  const [sortOrder, setSortOrder] = useState<TimelineSortOrder>(() => {
    if (typeof localStorage === 'undefined') {
      return 'desc'
    }
    const raw = localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY)
    return raw === 'asc' ? 'asc' : 'desc'
  })

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

  const handleMetricThresholdInputChange = useCallback(
    (
      rawValue: string,
      setInput: (value: string) => void,
      setValue: (value: number) => void,
    ) => {
      setInput(rawValue)
      if (rawValue.trim() === '') return
      const parsed = Number(rawValue)
      if (!isValidMetricThresholdPercent(parsed)) return
      setValue(parsed)
    },
    [],
  )

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

  const generateTimeline = useCallback(async () => {
    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    if (!resolved.from || !resolved.to) {
      onError('期間の開始と終了を指定してください。')
      return
    }
    const from = resolved.from
    const to = resolved.to
    onError(null)
    setLoading(true)
    try {
      const payload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: { from, to },
        options: {
          vcenterId,
          includePeriodMetricsCpu,
          includePeriodMetricsMemory,
          includePeriodMetricsDiskIo,
          includePeriodMetricsNetworkIo,
          metricThresholdCpuPct,
          metricThresholdMemoryPct,
          metricThresholdDiskPct,
          metricThresholdNetworkPct,
          alertTopN,
        },
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
  }, [
    includePeriodMetricsCpu,
    includePeriodMetricsDiskIo,
    includePeriodMetricsMemory,
    includePeriodMetricsNetworkIo,
    metricThresholdCpuPct,
    metricThresholdDiskPct,
    metricThresholdMemoryPct,
    metricThresholdNetworkPct,
    alertTopN,
    onError,
    rangeParts,
    timeZone,
    vcenterId,
    fetchManualSnapshotAuditItems,
  ])

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
    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok || !resolved.from || !resolved.to) {
      onError(resolved.ok ? '期間の開始と終了を指定してください。' : resolved.message)
      return
    }
    onError(null)
    setSavingSnapshot(true)
    try {
      const buildRequestPayload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: { from: resolved.from, to: resolved.to },
        options: {
          vcenterId,
          includePeriodMetricsCpu,
          includePeriodMetricsMemory,
          includePeriodMetricsDiskIo,
          includePeriodMetricsNetworkIo,
          metricThresholdCpuPct,
          metricThresholdMemoryPct,
          metricThresholdDiskPct,
          metricThresholdNetworkPct,
          alertTopN,
        },
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
    fetchManualSnapshotAuditItems,
    onError,
    operatorNote,
    rangeParts,
    timeZone,
    vcenterId,
    includePeriodMetricsCpu,
    includePeriodMetricsMemory,
    includePeriodMetricsDiskIo,
    includePeriodMetricsNetworkIo,
    metricThresholdCpuPct,
    metricThresholdMemoryPct,
    metricThresholdDiskPct,
    metricThresholdNetworkPct,
    alertTopN,
  ])

  return (
    <div className="panel timeline-panel">
      <TimelineFilters
        rangeParts={rangeParts}
        setRangeParts={setRangeParts}
        vcenters={vcenters}
        vcenterId={vcenterId}
        setVcenterId={setVcenterId}
        loading={loading}
        includePeriodMetricsCpu={includePeriodMetricsCpu}
        setIncludePeriodMetricsCpu={setIncludePeriodMetricsCpu}
        includePeriodMetricsMemory={includePeriodMetricsMemory}
        setIncludePeriodMetricsMemory={setIncludePeriodMetricsMemory}
        includePeriodMetricsDiskIo={includePeriodMetricsDiskIo}
        setIncludePeriodMetricsDiskIo={setIncludePeriodMetricsDiskIo}
        includePeriodMetricsNetworkIo={includePeriodMetricsNetworkIo}
        setIncludePeriodMetricsNetworkIo={setIncludePeriodMetricsNetworkIo}
        metricThresholdCpuInput={metricThresholdCpuInput}
        metricThresholdCpuPct={metricThresholdCpuPct}
        setMetricThresholdCpuInput={setMetricThresholdCpuInput}
        setMetricThresholdCpuPct={setMetricThresholdCpuPct}
        metricThresholdMemoryInput={metricThresholdMemoryInput}
        metricThresholdMemoryPct={metricThresholdMemoryPct}
        setMetricThresholdMemoryInput={setMetricThresholdMemoryInput}
        setMetricThresholdMemoryPct={setMetricThresholdMemoryPct}
        metricThresholdDiskInput={metricThresholdDiskInput}
        metricThresholdDiskPct={metricThresholdDiskPct}
        setMetricThresholdDiskInput={setMetricThresholdDiskInput}
        setMetricThresholdDiskPct={setMetricThresholdDiskPct}
        metricThresholdNetworkInput={metricThresholdNetworkInput}
        metricThresholdNetworkPct={metricThresholdNetworkPct}
        setMetricThresholdNetworkInput={setMetricThresholdNetworkInput}
        setMetricThresholdNetworkPct={setMetricThresholdNetworkPct}
        alertTopNInput={alertTopNInput}
        alertTopN={alertTopN}
        setAlertTopNInput={setAlertTopNInput}
        setAlertTopN={setAlertTopN}
        sortOrder={sortOrder}
        setSortOrder={setSortOrder}
        onMetricThresholdInputChange={handleMetricThresholdInputChange}
        onAlertTopNInputChange={handleAlertTopNInputChange}
        onAlertTopNBlur={() => setAlertTopNInput(String(alertTopN))}
      />

      <TimelineSnapshotActions
        loading={loading}
        savingSnapshot={savingSnapshot}
        hasTimeline={timeline != null}
        operatorNote={operatorNote}
        setOperatorNote={setOperatorNote}
        onGenerateTimeline={generateTimeline}
        onSaveSnapshot={saveManualSnapshot}
        manualSnapshotAuditItems={manualSnapshotAuditItems}
        selectedManualSnapshotId={selectedManualSnapshotId}
        setSelectedManualSnapshotId={setSelectedManualSnapshotId}
        onLoadTimelineFromSnapshot={loadTimelineFromSnapshot}
        onOpenSnapshotInMetrics={onOpenSnapshotInMetrics}
      />

      <TimelineResults
        timeline={timeline}
        sortOrder={sortOrder}
        snapshotMarkers={snapshotMarkers}
      />
    </div>
  )
}
