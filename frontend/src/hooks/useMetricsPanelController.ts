import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { LegendPayload } from 'recharts'
import { apiGet } from '../api'
import { asArray } from '../utils/asArray'
import {
  parseApiUtcInstantMs,
  formatChartAxisTick,
  formatChartTooltipLabel,
  type FormatChartAxisTickOptions,
} from '../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../datetime/useTimeZone'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  formatRollingDurationLabel,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'

/** グラフの表示期間がクイックプリセットに追従するか、手入力固定か。 */
export type GraphRangeFollowMode = 'rolling' | 'manual'
import {
  resolveMetricsGraphRange,
  summarizeGraphRangePreview,
} from '../datetime/graphRange'
import { buildMetricsChartModel } from '../metrics/buildMetricsChartModel'
import {
  buildMetricsChartSeriesIdentityKey,
  legendDataKeyToString,
  toggleHiddenSeriesDataKey,
} from '../metrics/metricsChartSeriesVisibility'
import type { MetricCsvExportOptions } from '../metrics/metricCsv'
import { formatChartYAxisTick } from '../metrics/chartYAxisFormat'
import { useChartThemeColors } from '../theme/useChartThemeColors'
import { useMetricDataFetch } from './useMetricDataFetch'

/** 系列 `tMs` の幅がこれ以下なら X 軸は月日を省略し時刻のみ */
const CHART_TIME_SPAN_OMIT_MONTH_DAY_MS = 2 * 86400000

export function useMetricsPanelController(
  onError: (e: string | null) => void,
  perfBucketSeconds: number,
) {
  const { timeZone } = useTimeZone()
  const [graphRangeFollowMode, setGraphRangeFollowMode] =
    useState<GraphRangeFollowMode>('rolling')
  const [rollingDurationMs, setRollingDurationMs] = useState(
    METRICS_DEFAULT_ROLLING_DURATION_MS,
  )
  const [vcenterId, setVcenterId] = useState('')
  const [metricKey, setMetricKey] = useState('')
  const [chartResetKey, setChartResetKey] = useState(0)
  const [chartEventType, setChartEventType] = useState('')
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([])
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(
      METRICS_DEFAULT_ROLLING_DURATION_MS,
      timeZone,
    ),
  )
  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )
  const prevTimeZoneRef = useRef<string | null>(null)
  const lastSeriesFetchRef = useRef<{
    vcenterId: string
    metricKey: string
    rangeKey: string
  } | null>(null)
  const chartWrapRef = useRef<HTMLDivElement>(null)
  const chartColors = useChartThemeColors()

  const {
    vcenters,
    metricKeys,
    points,
    metricTotal,
    loading,
    eventRateBuckets,
    eventSeriesLoading,
    loadMetricKeys,
    loadSeries,
  } = useMetricDataFetch({
    vcenterId,
    metricKey,
    rangeFromInput,
    rangeToInput,
    timeZone,
    perfBucketSeconds,
    chartEventType,
    onError,
  })

  // Initialize vcenterId and metricKey if not set
  useEffect(() => {
    if (!vcenterId && vcenters.length > 0) {
      setVcenterId(vcenters[0].id)
    }
  }, [vcenters, vcenterId])

  useEffect(() => {
    if (!metricKey && metricKeys.length > 0) {
      setMetricKey(metricKeys[0])
    }
  }, [metricKeys, metricKey])

  const onGraphRangeFieldsChange = useCallback((next: ZonedRangeParts) => {
    setGraphRangeFollowMode('manual')
    setRangeParts(next)
  }, [])

  const applyRollingPreset = useCallback(
    (durationMs: number) => {
      setGraphRangeFollowMode('rolling')
      setRollingDurationMs(durationMs)
      setRangeParts(presetRelativeRangeWallPartsWithUtcFallback(durationMs, timeZone))
    },
    [timeZone],
  )

  useEffect(() => {
    if (prevTimeZoneRef.current === null) {
      prevTimeZoneRef.current = timeZone
      return
    }
    if (prevTimeZoneRef.current === timeZone) return
    prevTimeZoneRef.current = timeZone
    if (graphRangeFollowMode !== 'rolling') return
    setRangeParts(presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone))
    lastSeriesFetchRef.current = null
  }, [timeZone, graphRangeFollowMode, rollingDurationMs])

  useEffect(() => {
    const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
    void apiGet<{ event_types?: unknown }>(`/api/events/event-types${q}`)
      .then((d) => setEventTypeOptions(asArray<string>(d.event_types)))
      .catch(() => setEventTypeOptions([]))
  }, [vcenterId])

  useEffect(() => {
    void (async () => {
      let key = metricKey
      if (lastSeriesFetchRef.current?.vcenterId !== vcenterId) {
        key = await loadMetricKeys()
        setMetricKey(key)
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
      const ok = await loadSeries(key)
      if (ok) lastSeriesFetchRef.current = sig
    })()
  }, [vcenterId, metricKey, loadSeries, loadMetricKeys, rangeParts])

  const graphRangeForOverlay = useMemo(
    () => resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone),
    [rangeFromInput, rangeToInput, timeZone],
  )

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

  /** 下余白は `MetricsPanel` で `xAxisBottomMarginForWidth` と合成する */
  const metricsChartMargin = useMemo(
    () => ({
      /** 上部凡例（多系列・長文で折り返しあり）用 */
      top: 44,
      right: showEventLine ? 56 : 48,
      left: leftYAxisLabel ? 58 : 52,
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

  const [hiddenSeriesDataKeys, setHiddenSeriesDataKeys] = useState<Set<string>>(() => new Set())

  const seriesIdentityKey = useMemo(
    () =>
      buildMetricsChartSeriesIdentityKey({
        metricKey,
        chartMode: chartModel.mode === 'single' ? 'single' : 'host',
        metricSeriesDataKeys: chartModel.metricSeries.map((s) => s.dataKey),
        showEventLine,
      }),
    [metricKey, chartModel, showEventLine],
  )

  useEffect(() => {
    setHiddenSeriesDataKeys(new Set())
  }, [seriesIdentityKey])

  const onMetricsLegendClick = useCallback((data: LegendPayload) => {
    const key = legendDataKeyToString(data.dataKey)
    if (key === null) return
    setHiddenSeriesDataKeys((prev) => toggleHiddenSeriesDataKey(prev, key))
  }, [])

  const chartData = chartModel.rows

  const chartAxisTickFormatOptions = useMemo((): FormatChartAxisTickOptions => {
    if (chartData.length === 0) {
      return { omitMonthDay: false }
    }
    let minT = chartData[0].tMs
    let maxT = chartData[0].tMs
    for (let i = 1; i < chartData.length; i++) {
      const t = chartData[i].tMs
      if (t < minT) minT = t
      if (t > maxT) maxT = t
    }
    const spanMs = maxT - minT
    // 年省略判定の「今」は表示系列の終端に固定し、ツールチップ／軸／再レンダー間で Date.now() 揺れを防ぐ
    return {
      omitMonthDay: spanMs <= CHART_TIME_SPAN_OMIT_MONTH_DAY_MS,
      nowMs: maxT,
    }
  }, [chartData])

  const vcenterLabelForChart = useMemo(() => {
    if (!vcenterId) return '全て'
    const v = vcenters.find((c) => c.id === vcenterId)
    return v?.name ?? vcenterId
  }, [vcenterId, vcenters])

  /** グラフ見出し・表示期間サマリー共通。ローリング時は「直近24時間」表記で誤解を防ぐ。 */
  const graphRangeDisplayLabel = useMemo(() => {
    if (graphRangeFollowMode === 'rolling') {
      return formatRollingDurationLabel(rollingDurationMs)
    }
    return summarizeGraphRangePreview(rangeParts)
  }, [graphRangeFollowMode, rollingDurationMs, rangeParts])

  const metricsChartTitleLines = useMemo(() => {
    const mk = metricKey.trim() || '—'
    const line1 = `${vcenterLabelForChart} / ${mk}`
    const et = chartEventType.trim()
    const line2Parts: string[] = []
    if (et) line2Parts.push(`イベント種別: ${et}`)
    line2Parts.push(`期間: ${graphRangeDisplayLabel}`)
    const line2 = line2Parts.join(' · ')
    return { line1, line2 }
  }, [vcenterLabelForChart, metricKey, chartEventType, graphRangeDisplayLabel])

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
    (value: unknown) => formatChartAxisTick(value, timeZone, chartAxisTickFormatOptions),
    [timeZone, chartAxisTickFormatOptions],
  )

  const formatTooltipLabel = useCallback(
    (value: unknown) => formatChartTooltipLabel(value, timeZone, chartAxisTickFormatOptions),
    [timeZone, chartAxisTickFormatOptions],
  )

  const formatYAxisTickMetric = useCallback(
    (value: number) => formatChartYAxisTick(value, 'metric', metricKey),
    [metricKey],
  )

  const formatYAxisTickCount = useCallback(
    (value: number) => formatChartYAxisTick(value, 'count'),
    [],
  )

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

  const runMetricsAutoRefresh = useCallback(() => {
    invalidateSeriesCache()
    if (graphRangeFollowMode === 'rolling') {
      setRangeParts(
        presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone),
      )
      return
    }
    void loadSeries(metricKey, { silent: true })
  }, [
    graphRangeFollowMode,
    invalidateSeriesCache,
    loadSeries,
    metricKey,
    rollingDurationMs,
    timeZone,
  ])

  const reloadMetricsSeries = useCallback(() => {
    invalidateSeriesCache()
    if (graphRangeFollowMode === 'rolling') {
      setRangeParts(
        presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone),
      )
      return
    }
    void loadSeries(metricKey)
  }, [graphRangeFollowMode, invalidateSeriesCache, loadSeries, metricKey, rollingDurationMs, timeZone])

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
    chartResetKey,
    setChartResetKey,
    chartEventType,
    setChartEventType,
    eventTypeOptions,
    rangeParts,
    graphRangeFollowMode,
    onGraphRangeFieldsChange,
    applyRollingPreset,
    chartWrapRef,
    chartColors,
    invalidateSeriesCache,
    loadSeries,
    runMetricsAutoRefresh,
    reloadMetricsSeries,
    loadMetricKeys,
    graphRangeForOverlay,
    showEventLine,
    leftYAxisLabel,
    metricsChartMargin,
    chartModel,
    chartData,
    hiddenSeriesDataKeys,
    onMetricsLegendClick,
    vcenterLabelForChart,
    metricsChartTitleLines,
    graphRangeDisplayLabel,
    metricsChartLegendName,
    eventSeriesLegendName,
    chartAxisTickFormatOptions,
    formatAxisTimeLabel,
    formatTooltipLabel,
    formatYAxisTickMetric,
    formatYAxisTickCount,
    vcenterExportLabel,
    eventSeriesLoading,
    countByEpochSec,
    csvExportOptions,
    exportDisabled,
  }
}
