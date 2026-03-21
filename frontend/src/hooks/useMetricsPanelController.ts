import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiGet, apiPost } from '../api'
import type { VCenter } from '../api/schemas'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'
import {
  parseApiUtcInstantMs,
  formatChartAxisTick,
} from '../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../datetime/useTimeZone'
import {
  EMPTY_ZONED_RANGE_PARTS,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'
import {
  resolveMetricsGraphRange,
  summarizeGraphRangePreview,
} from '../datetime/graphRange'
import { buildMetricsChartModel } from '../metrics/buildMetricsChartModel'
import {
  normalizeMetricSeriesResponse,
  type MetricPoint,
} from '../metrics/normalizeMetricSeriesResponse'
import type { MetricCsvExportOptions } from '../metrics/metricCsv'
import { mergeMetricKeyOptions } from '../metrics/knownMetricKeys'
import { useChartThemeColors } from '../theme/useChartThemeColors'

export function useMetricsPanelController(
  onError: (e: string | null) => void,
  perfBucketSeconds: number,
) {
  const { timeZone } = useTimeZone()
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [vcenterId, setVcenterId] = useState('')
  const [metricKeys, setMetricKeys] = useState<string[]>(() => mergeMetricKeyOptions([]))
  const [metricKey, setMetricKey] = useState(
    () => mergeMetricKeyOptions([])[0] ?? '',
  )
  const [points, setPoints] = useState<MetricPoint[]>([])
  const [metricTotal, setMetricTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [chartResetKey, setChartResetKey] = useState(0)
  const [chartEventType, setChartEventType] = useState('')
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([])
  const [eventRateBuckets, setEventRateBuckets] = useState<
    Array<{ bucket_start: string; count: number }> | null
  >(null)
  const [eventSeriesLoading, setEventSeriesLoading] = useState(false)
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(EMPTY_ZONED_RANGE_PARTS)
  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )
  const prevVcenterForKeysRef = useRef<string | undefined>(undefined)
  const lastSeriesFetchRef = useRef<{
    vcenterId: string
    metricKey: string
    rangeKey: string
  } | null>(null)
  const metricKeyRef = useRef(metricKey)
  const chartWrapRef = useRef<HTMLDivElement>(null)
  const chartColors = useChartThemeColors()
  metricKeyRef.current = metricKey

  useEffect(() => {
    void apiGet<unknown>('/api/vcenters')
      .then((v) => {
        const arr = asArray<VCenter>(v)
        setVcenters(arr)
        setVcenterId((prev) => prev || arr[0]?.id || '')
      })
      .catch((e) => onError(toErrorMessage(e)))
  }, [onError])

  useEffect(() => {
    const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
    void apiGet<{ event_types?: unknown }>(`/api/events/event-types${q}`)
      .then((d) => setEventTypeOptions(asArray<string>(d.event_types)))
      .catch(() => setEventTypeOptions([]))
  }, [vcenterId])

  const loadMetricKeys = useCallback(async (): Promise<string> => {
    try {
      const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
      const data = await apiGet<{ metric_keys?: unknown }>(`/api/metrics/keys${q}`)
      const keys = mergeMetricKeyOptions(asArray<string>(data.metric_keys))
      // Read ref after await so we respect metric key changes during the request.
      const prev = metricKeyRef.current
      const nextKey = keys.includes(prev) ? prev : (keys[0] ?? '')
      setMetricKeys(keys)
      setMetricKey(nextKey)
      return nextKey
    } catch (e) {
      onError(toErrorMessage(e))
      const keys = mergeMetricKeyOptions([])
      const prev = metricKeyRef.current
      const nextKey = keys.includes(prev) ? prev : (keys[0] ?? '')
      setMetricKeys(keys)
      setMetricKey(nextKey)
      return nextKey
    }
  }, [vcenterId, onError])

  const load = useCallback(
    async (overrideKey?: string): Promise<boolean> => {
      const graphRange = resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone)
      if (graphRange.mode === 'invalid') {
        onError(graphRange.message)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      const key = (overrideKey ?? metricKey).trim()
      if (!key) {
        onError(null)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      setLoading(true)
      onError(null)
      try {
        const limit = graphRange.mode === 'range' ? '10000' : '500'
        const q = new URLSearchParams({ metric_key: key, limit })
        if (vcenterId) q.set('vcenter_id', vcenterId)
        if (graphRange.mode === 'range') {
          q.set('from', graphRange.from)
          q.set('to', graphRange.to)
        }
        const data = await apiGet<unknown>(`/api/metrics?${q.toString()}`)
        const normalized = normalizeMetricSeriesResponse(data)
        setPoints(normalized.points)
        setMetricTotal(normalized.total)
        return true
      } catch (e) {
        onError(toErrorMessage(e))
        return false
      } finally {
        setLoading(false)
      }
    },
    [vcenterId, metricKey, onError, rangeFromInput, rangeToInput, timeZone],
  )

  const graphRangeForOverlay = useMemo(
    () => resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone),
    [rangeFromInput, rangeToInput, timeZone],
  )

  useEffect(() => {
    void (async () => {
      let key = metricKey
      if (prevVcenterForKeysRef.current !== vcenterId) {
        prevVcenterForKeysRef.current = vcenterId
        key = await loadMetricKeys()
      }
      const rangeKey = `${rangeParts.fromDate}|${rangeParts.fromTime}|${rangeParts.toDate}|${rangeParts.toTime}`
      const sig = { vcenterId, metricKey: key, rangeKey }
      const prev = lastSeriesFetchRef.current
      if (
        prev &&
        prev.vcenterId === sig.vcenterId &&
        prev.metricKey === sig.metricKey &&
        prev.rangeKey === sig.rangeKey
      ) {
        return
      }
      const ok = await load(key)
      if (ok) lastSeriesFetchRef.current = sig
    })()
  }, [vcenterId, metricKey, load, loadMetricKeys, rangeParts])

  useEffect(() => {
    const et = chartEventType.trim()
    if (!et || points.length === 0) {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    if (graphRangeForOverlay.mode === 'invalid') {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    let cancelled = false
    setEventSeriesLoading(true)
    void (async () => {
      let from: string
      let to: string
      if (graphRangeForOverlay.mode === 'range') {
        from = graphRangeForOverlay.from
        to = graphRangeForOverlay.to
      } else {
        let minTs = Infinity
        let maxTs = -Infinity
        for (const p of points) {
          const t = parseApiUtcInstantMs(p.sampled_at)
          if (Number.isFinite(t)) {
            if (t < minTs) minTs = t
            if (t > maxTs) maxTs = t
          }
        }
        if (!Number.isFinite(minTs) || !Number.isFinite(maxTs)) {
          if (!cancelled) {
            setEventRateBuckets(null)
            setEventSeriesLoading(false)
          }
          return
        }
        from = new Date(minTs).toISOString()
        to = new Date(maxTs).toISOString()
      }
      const fromMs = parseApiUtcInstantMs(from)
      const toMs = parseApiUtcInstantMs(to)
      if (fromMs >= toMs) {
        to = new Date(fromMs + Math.max(perfBucketSeconds, 60) * 1000).toISOString()
      }
      try {
        const q = new URLSearchParams({
          event_type: et,
          from,
          to,
          bucket_seconds: String(perfBucketSeconds),
        })
        if (vcenterId) q.set('vcenter_id', vcenterId)
        const data = await apiGet<{
          buckets?: Array<{ bucket_start: string; count: number }>
        }>(`/api/events/rate-series?${q.toString()}`)
        if (!cancelled) {
          setEventRateBuckets(Array.isArray(data.buckets) ? data.buckets : [])
          onError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setEventRateBuckets(null)
          onError(toErrorMessage(e))
        }
      } finally {
        if (!cancelled) setEventSeriesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [points, chartEventType, vcenterId, perfBucketSeconds, onError, graphRangeForOverlay])

  const runIngest = async () => {
    setIngesting(true)
    onError(null)
    try {
      await apiPost<{ status: string; events_inserted: number; metrics_inserted: number }>(
        '/api/ingest/run',
        {},
      )
      lastSeriesFetchRef.current = null
      const key = await loadMetricKeys()
      await load(key)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setIngesting(false)
    }
  }

  const countByEpochSec = useMemo(() => {
    const m = new Map<number, number>()
    if (!eventRateBuckets) return m
    for (const b of eventRateBuckets) {
      const sec = Math.floor(parseApiUtcInstantMs(String(b.bucket_start)) / 1000)
      m.set(sec, b.count)
    }
    return m
  }, [eventRateBuckets])

  const showEventLine =
    chartEventType.trim().length > 0 && eventRateBuckets != null && !eventSeriesLoading

  const leftYAxisLabel = useMemo(() => {
    const k = metricKey.trim()
    return k.endsWith('_pct') ? '％' : undefined
  }, [metricKey])

  const metricsChartMargin = useMemo(
    () => ({
      top: 8,
      right: showEventLine ? 44 : 12,
      left: leftYAxisLabel ? 32 : 8,
      bottom: 8,
    }),
    [showEventLine, leftYAxisLabel],
  )

  const chartModel = useMemo(
    () =>
      buildMetricsChartModel(
        metricKey,
        points ?? [],
        perfBucketSeconds,
        showEventLine,
        countByEpochSec,
      ),
    [metricKey, points, perfBucketSeconds, showEventLine, countByEpochSec],
  )

  const chartData = chartModel.rows

  const vcenterLabelForChart = useMemo(() => {
    if (!vcenterId) return '全て'
    const v = vcenters.find((c) => c.id === vcenterId)
    return v?.name ?? vcenterId
  }, [vcenterId, vcenters])

  const metricsChartTitleLines = useMemo(() => {
    const mk = metricKey.trim() || '—'
    const line1 = `${vcenterLabelForChart} / ${mk}`
    const et = chartEventType.trim()
    const rangeLabel = summarizeGraphRangePreview(rangeParts)
    const line2Parts: string[] = []
    if (et) line2Parts.push(`イベント種別: ${et}`)
    line2Parts.push(`期間: ${rangeLabel}`)
    const line2 = line2Parts.join(' · ')
    return { line1, line2 }
  }, [vcenterLabelForChart, metricKey, chartEventType, rangeParts])

  const metricsChartLegendName = useMemo(() => {
    const keyPart = metricKey || '—'
    if (!vcenterId) {
      return `全て / ${keyPart}`
    }
    const v = vcenters.find((c) => c.id === vcenterId)
    const vcLabel = v?.name ?? vcenterId
    return `${vcLabel} / ${keyPart}`
  }, [vcenterId, vcenters, metricKey])

  const eventSeriesLegendName = useMemo(() => {
    const et = chartEventType.trim()
    if (!et) return 'イベント件数'
    return `イベント（${et}）`
  }, [chartEventType])

  const formatAxisTimeLabel = useCallback(
    (value: unknown) => formatChartAxisTick(value, timeZone),
    [timeZone],
  )

  const formatYAxisTick = useCallback((value: number) => {
    if (!Number.isFinite(value)) return ''
    if (Math.abs(value) >= 10) return String(Math.round(value))
    return String(value)
  }, [])

  const vcenterExportLabel = useMemo(() => {
    if (!vcenterId) return 'all'
    const v = vcenters.find((c) => c.id === vcenterId)
    return v?.name ?? vcenterId
  }, [vcenterId, vcenters])

  const csvExportOptions: MetricCsvExportOptions | undefined = useMemo(() => {
    const et = chartEventType.trim()
    if (!et || !eventRateBuckets) return undefined
    return {
      bucketSeconds: perfBucketSeconds,
      eventCountByBucketEpochSec: countByEpochSec,
      overlayEventType: et,
    }
  }, [chartEventType, eventRateBuckets, perfBucketSeconds, countByEpochSec])

  const exportDisabled =
    loading || !metricKey || points.length === 0 || eventSeriesLoading

  const invalidateSeriesCache = useCallback(() => {
    lastSeriesFetchRef.current = null
  }, [])

  return {
    timeZone,
    vcenters,
    vcenterId,
    setVcenterId,
    metricKeys,
    metricKey,
    setMetricKey,
    points,
    metricTotal,
    loading,
    ingesting,
    chartResetKey,
    setChartResetKey,
    chartEventType,
    setChartEventType,
    eventTypeOptions,
    rangeParts,
    setRangeParts,
    chartWrapRef,
    chartColors,
    invalidateSeriesCache,
    load,
    loadMetricKeys,
    runIngest,
    graphRangeForOverlay,
    showEventLine,
    leftYAxisLabel,
    metricsChartMargin,
    chartModel,
    chartData,
    vcenterLabelForChart,
    metricsChartTitleLines,
    metricsChartLegendName,
    eventSeriesLegendName,
    formatAxisTimeLabel,
    formatYAxisTick,
    vcenterExportLabel,
    eventSeriesLoading,
    countByEpochSec,
    csvExportOptions,
    exportDisabled,
  }
}
