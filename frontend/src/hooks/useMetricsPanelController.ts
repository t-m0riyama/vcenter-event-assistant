import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../api'
import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../datetime/useTimeZone'
import { asArray } from '../utils/asArray'
import { useGraphRangeState } from './useGraphRangeState'
import { resolveMetricsReplay, type MetricsReplayInput } from './metricsReplay'
import { useMetricDataFetch } from './useMetricDataFetch'
import { useMetricsChartSeries } from './useMetricsChartSeries'
import { useMetricsExport } from './useMetricsExport'

export type {
  GraphRangeFollowMode,
  MetricsSnapshotReplayInput,
  MetricsReplayInput,
} from './useGraphRangeState'

/** メトリクスパネルの状態・取得・チャート表示を統合するコントローラ。 */
export function useMetricsPanelController(
  onError: (e: string | null) => void,
  perfBucketSeconds: number,
  snapshotReplay?: MetricsReplayInput | null,
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
  const [pendingMetricKey, setPendingMetricKey] = useState<{ key: string; nonce: number } | null>(null)
  const consumedPendingNonceRef = useRef(0)
  const [chartGuidelineLabel, setChartGuidelineLabel] = useState('スナップショット')
  const replay = resolveMetricsReplay(snapshotReplay)
  const snapshotItem = replay?.source
  const snapshotNonce = replay?.nonce
  const [appliedSnapshot, setAppliedSnapshot] = useState<{
    item: object | undefined
    nonce: number | undefined
  }>({ item: undefined, nonce: undefined })

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

  if (appliedSnapshot.item !== snapshotItem || appliedSnapshot.nonce !== snapshotNonce) {
    setAppliedSnapshot({ item: snapshotItem, nonce: snapshotNonce })
    if (!replay) {
      setSnapshotChartGuidelineMs(null)
    } else {
      setVcenterId(replay.vcenterId)
      if (replay.kind === 'snapshot') {
        setMetricKey(replay.metricKey)
        setPendingMetricKey(null)
      } else {
        // focus: 指定があれば、系列の一覧を読んでから選べるときだけ選ぶ。無ければ今の指標を保つ
        setPendingMetricKey(replay.metricKey ? { key: replay.metricKey, nonce: replay.nonce } : null)
      }
      setChartEventType(replay.chartEventType)
      const markerMs = replay.markerUtc ? parseApiUtcInstantMs(replay.markerUtc) : NaN
      setSnapshotChartGuidelineMs(Number.isFinite(markerMs) ? markerMs : null)
      setChartGuidelineLabel(replay.markerLabel)
      setChartResetKey((k) => k + 1)
    }
  } else if (!metricKey && metricKeys.length > 0) {
    setMetricKey(metricKeys[0])
  }

  useEffect(() => {
    if (snapshotItem && snapshotNonce !== undefined && snapshotNonce > 0) {
      invalidateSeriesCache()
    }
  }, [snapshotItem, snapshotNonce, invalidateSeriesCache])

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
        const want =
          pendingMetricKey && pendingMetricKey.nonce > consumedPendingNonceRef.current ? pendingMetricKey : null
        key = await loadMetricKeys(want?.key)
        if (generation !== seriesFetchEffectGenerationRef.current) return
        if (want) consumedPendingNonceRef.current = want.nonce
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
  }, [vcenterId, metricKey, loadSeries, loadMetricKeys, rangeParts, pendingMetricKey])

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
    chartGuidelineLabel,
    graphRangeDisplayLabel,
    ...chart,
    ...metricsExport,
  }
}
