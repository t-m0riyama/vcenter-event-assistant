import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../api'
import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../datetime/useTimeZone'
import { asArray } from '../utils/asArray'
import {
  useGraphRangeState,
  type MetricsSnapshotReplayInput,
} from './useGraphRangeState'
import { useMetricDataFetch } from './useMetricDataFetch'
import { useMetricsChartSeries } from './useMetricsChartSeries'
import { useMetricsExport } from './useMetricsExport'

export type { GraphRangeFollowMode, MetricsSnapshotReplayInput } from './useGraphRangeState'

/** メトリクスパネルの状態・取得・チャート表示を統合するコントローラ。 */
export function useMetricsPanelController(
  onError: (e: string | null) => void,
  perfBucketSeconds: number,
  snapshotReplay?: MetricsSnapshotReplayInput | null,
) {
  const { timeZone } = useTimeZone()
  const [vcenterId, setVcenterId] = useState('')
  const [metricKey, setMetricKey] = useState('')
  const [chartResetKey, setChartResetKey] = useState(0)
  const [chartEventType, setChartEventType] = useState('')
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([])
  const lastSeriesFetchRef = useRef<{
    vcenterId: string
    metricKey: string
    rangeKey: string
  } | null>(null)
  const seriesFetchEffectGenerationRef = useRef(0)
  const [snapshotChartGuidelineMs, setSnapshotChartGuidelineMs] = useState<number | null>(null)

  const invalidateSeriesCache = useCallback(() => {
    lastSeriesFetchRef.current = null
  }, [])

  const {
    graphRangeFollowMode,
    rangeParts,
    rangeFromInput,
    rangeToInput,
    onGraphRangeFieldsChange,
    applyRollingPreset,
    graphRangeForOverlay,
    graphRangeDisplayLabel,
    refreshRollingRange,
  } = useGraphRangeState(timeZone, snapshotReplay, {
    onRollingRangeInvalidated: invalidateSeriesCache,
  })

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

  useEffect(() => {
    if (!snapshotReplay?.item || snapshotReplay.nonce < 1) {
      setSnapshotChartGuidelineMs(null)
      return
    }
    const { item } = snapshotReplay
    const br = item.build_request_payload
    const gc = item.graph_context
    const vid = gc?.vcenter_id ?? br.vcenter_id
    setVcenterId(vid && String(vid).length > 0 ? String(vid) : '')
    setMetricKey(gc?.metric_key ?? '')
    setChartEventType(gc?.chart_event_type ?? '')
    const markerSrc = gc?.marker_timestamp_utc ?? item.timestamp_utc
    setSnapshotChartGuidelineMs(parseApiUtcInstantMs(String(markerSrc)))
    invalidateSeriesCache()
    setChartResetKey((k) => k + 1)
  }, [snapshotReplay?.item, snapshotReplay?.nonce, invalidateSeriesCache])

  useEffect(() => {
    if (!metricKey && metricKeys.length > 0) {
      setMetricKey(metricKeys[0])
    }
  }, [metricKeys, metricKey])

  useEffect(() => {
    const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
    void apiGet<{ event_types?: unknown }>(`/api/events/event-types${q}`)
      .then((d) => setEventTypeOptions(asArray<string>(d.event_types)))
      .catch(() => setEventTypeOptions([]))
  }, [vcenterId])

  useEffect(() => {
    const generation = ++seriesFetchEffectGenerationRef.current
    void (async () => {
      let key = metricKey
      if (lastSeriesFetchRef.current?.vcenterId !== vcenterId) {
        key = await loadMetricKeys()
        if (generation !== seriesFetchEffectGenerationRef.current) return
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
      if (generation !== seriesFetchEffectGenerationRef.current) return
      if (ok) lastSeriesFetchRef.current = sig
    })()
  }, [vcenterId, metricKey, loadSeries, loadMetricKeys, rangeParts])

  const chart = useMetricsChartSeries({
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
  })

  const metricsExport = useMetricsExport({
    vcenterId,
    vcenters,
    metricKey,
    points,
    loading,
    eventSeriesLoading,
    chartEventType,
    eventRateBuckets,
    perfBucketSeconds,
    countByEpochSec: chart.countByEpochSec,
  })

  const runMetricsAutoRefresh = useCallback(() => {
    invalidateSeriesCache()
    if (graphRangeFollowMode === 'rolling') {
      refreshRollingRange()
      return
    }
    void loadSeries(metricKey, { silent: true })
  }, [
    graphRangeFollowMode,
    invalidateSeriesCache,
    loadSeries,
    metricKey,
    refreshRollingRange,
  ])

  const reloadMetricsSeries = useCallback(() => {
    invalidateSeriesCache()
    if (graphRangeFollowMode === 'rolling') {
      refreshRollingRange()
      return
    }
    void loadSeries(metricKey)
  }, [graphRangeFollowMode, invalidateSeriesCache, loadSeries, metricKey, refreshRollingRange])

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
    onGraphRangeFieldsChange,
    applyRollingPreset,
    invalidateSeriesCache,
    loadSeries,
    runMetricsAutoRefresh,
    reloadMetricsSeries,
    loadMetricKeys,
    graphRangeForOverlay,
    eventSeriesLoading,
    snapshotChartGuidelineMs,
    graphRangeDisplayLabel,
    ...chart,
    ...metricsExport,
  }
}
