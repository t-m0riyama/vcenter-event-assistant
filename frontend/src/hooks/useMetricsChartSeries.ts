import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { LegendPayload } from 'recharts'
import type { VCenter } from '../api/schemas'
import type { MetricPoint } from '../metrics/normalizeMetricSeriesResponse'
import {
  parseApiUtcInstantMs,
  formatChartAxisTick,
  formatChartTooltipLabel,
  type FormatChartAxisTickOptions,
} from '../datetime/formatIsoInTimeZone'
import {
  buildMetricsChartModel,
  formatMetricChartSeriesLegendName,
} from '../metrics/buildMetricsChartModel'
import { formatChartYAxisTick } from '../metrics/chartYAxisFormat'
import {
  buildMetricsChartSeriesIdentityKey,
  legendDataKeyToString,
  toggleHiddenSeriesDataKey,
} from '../metrics/metricsChartSeriesVisibility'
import { useChartThemeColors } from '../theme/useChartThemeColors'

/** 系列 `tMs` の幅がこれ以下なら X 軸は月日を省略し時刻のみ */
const CHART_TIME_SPAN_OMIT_MONTH_DAY_MS = 2 * 86400000

type UseMetricsChartSeriesParams = {
  timeZone: string
  metricKey: string
  vcenterId: string
  vcenters: VCenter[]
  points: MetricPoint[]
  perfBucketSeconds: number
  chartEventType: string
  eventRateBuckets: { bucket_start: string; count: number }[] | null
  eventSeriesLoading: boolean
  graphRangeDisplayLabel: string
}

export function useMetricsChartSeries({
  timeZone,
  metricKey,
  vcenterId,
  vcenters,
  points,
  perfBucketSeconds,
  chartEventType,
  eventRateBuckets,
  eventSeriesLoading,
  graphRangeDisplayLabel,
}: UseMetricsChartSeriesParams) {
  const chartWrapRef = useRef<HTMLDivElement>(null)
  const chartColors = useChartThemeColors()

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
      top: 44,
      right: showEventLine ? 56 : 48,
      left: leftYAxisLabel ? 58 : 52,
    }),
    [showEventLine, leftYAxisLabel],
  )

  const vcenterNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const v of vcenters) {
      m.set(v.id, v.name)
    }
    return m
  }, [vcenters])

  const chartModel = useMemo(
    () =>
      buildMetricsChartModel(
        metricKey,
        points ?? [],
        perfBucketSeconds,
        showEventLine,
        countByEpochSec,
        vcenterNameById,
        !vcenterId,
      ),
    [
      metricKey,
      points,
      perfBucketSeconds,
      showEventLine,
      countByEpochSec,
      vcenterNameById,
      vcenterId,
    ],
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

  return {
    chartWrapRef,
    chartColors,
    countByEpochSec,
    showEventLine,
    leftYAxisLabel,
    metricsChartMargin,
    chartModel,
    chartData,
    hiddenSeriesDataKeys,
    onMetricsLegendClick,
    vcenterLabelForChart,
    formatMetricChartSeriesLegendName,
    metricsChartTitleLines,
    metricsChartLegendName,
    eventSeriesLegendName,
    chartAxisTickFormatOptions,
    formatAxisTimeLabel,
    formatTooltipLabel,
    formatYAxisTickMetric,
    formatYAxisTickCount,
  }
}
