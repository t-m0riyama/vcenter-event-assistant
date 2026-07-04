import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../api'
import type { VCenter } from '../api/schemas'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'
import { resolveMetricsGraphRange } from '../datetime/graphRange'
import { computeEventRateOverlayRange } from '../metrics/computeEventRateOverlayRange'
import {
  fetchMetricKeysForVcenter,
  pickMetricKeyAfterFetch,
} from '../metrics/fetchMetricKeys'
import {
  normalizeMetricSeriesResponse,
  type MetricPoint,
} from '../metrics/normalizeMetricSeriesResponse'
import { mergeMetricKeyOptions } from '../metrics/knownMetricKeys'

export interface UseMetricDataFetchOptions {
  vcenterId: string
  metricKey: string
  rangeFromInput: string
  rangeToInput: string
  timeZone: string
  perfBucketSeconds: number
  chartEventType: string
  onError: (e: string | null) => void
}

export function useMetricDataFetch(options: UseMetricDataFetchOptions) {
  const {
    vcenterId,
    metricKey,
    rangeFromInput,
    rangeToInput,
    timeZone,
    perfBucketSeconds,
    chartEventType,
    onError,
  } = options

  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [metricKeys, setMetricKeys] = useState<string[]>(() => mergeMetricKeyOptions([]))
  const [points, setPoints] = useState<MetricPoint[]>([])
  const [metricTotal, setMetricTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [eventRateBuckets, setEventRateBuckets] = useState<
    Array<{ bucket_start: string; count: number }> | null
  >(null)
  const [eventSeriesLoading, setEventSeriesLoading] = useState(false)

  const metricKeyRef = useRef(metricKey)
  metricKeyRef.current = metricKey
  const loadSeriesGenerationRef = useRef(0)
  const eventRateGenerationRef = useRef(0)

  useEffect(() => {
    void apiGet<unknown>('/api/vcenters')
      .then((v) => {
        setVcenters(asArray<VCenter>(v))
      })
      .catch((e) => onError(toErrorMessage(e)))
  }, [onError])

  const loadMetricKeys = useCallback(async (): Promise<string> => {
    try {
      const keys = await fetchMetricKeysForVcenter(vcenterId)
      const prev = metricKeyRef.current
      const nextKey = pickMetricKeyAfterFetch(prev, keys)
      setMetricKeys(keys)
      return nextKey
    } catch (e) {
      onError(toErrorMessage(e))
      const keys = mergeMetricKeyOptions([])
      const prev = metricKeyRef.current
      const nextKey = pickMetricKeyAfterFetch(prev, keys)
      setMetricKeys(keys)
      return nextKey
    }
  }, [vcenterId, onError])

  const loadSeries = useCallback(
    async (overrideKey?: string, fetchOptions?: { silent?: boolean }): Promise<boolean> => {
      const generation = ++loadSeriesGenerationRef.current
      const silent = fetchOptions?.silent === true
      const graphRange = resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone)
      if (graphRange.mode === 'invalid') {
        if (generation !== loadSeriesGenerationRef.current) return false
        onError(graphRange.message)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      const key = (overrideKey ?? metricKey).trim()
      if (!key) {
        if (generation !== loadSeriesGenerationRef.current) return false
        onError(null)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      if (!silent) setLoading(true)
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
        if (generation !== loadSeriesGenerationRef.current) return false
        const normalized = normalizeMetricSeriesResponse(data)
        setPoints(normalized.points)
        setMetricTotal(normalized.total)
        return true
      } catch (e) {
        if (generation !== loadSeriesGenerationRef.current) return false
        onError(toErrorMessage(e))
        return false
      } finally {
        if (generation === loadSeriesGenerationRef.current) {
          setLoading(false)
        }
      }
    },
    [vcenterId, metricKey, onError, rangeFromInput, rangeToInput, timeZone],
  )

  useEffect(() => {
    const et = chartEventType.trim()
    if (!et || points.length === 0) {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    const graphRange = resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone)
    if (graphRange.mode === 'invalid') {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    const generation = ++eventRateGenerationRef.current
    setEventSeriesLoading(true)
    void (async () => {
      const bounds = computeEventRateOverlayRange(graphRange, points, perfBucketSeconds)
      if (!bounds) {
        if (generation === eventRateGenerationRef.current) {
          setEventRateBuckets(null)
          setEventSeriesLoading(false)
        }
        return
      }
      const { from, to } = bounds
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
        if (generation !== eventRateGenerationRef.current) return
        setEventRateBuckets(Array.isArray(data.buckets) ? data.buckets : [])
        onError(null)
      } catch (e) {
        if (generation !== eventRateGenerationRef.current) return
        setEventRateBuckets(null)
        onError(toErrorMessage(e))
      } finally {
        if (generation === eventRateGenerationRef.current) {
          setEventSeriesLoading(false)
        }
      }
    })()
  }, [points, chartEventType, vcenterId, perfBucketSeconds, onError, rangeFromInput, rangeToInput, timeZone])

  return {
    vcenters,
    metricKeys,
    points,
    metricTotal,
    loading,
    eventRateBuckets,
    eventSeriesLoading,
    loadMetricKeys,
    loadSeries,
  }
}
