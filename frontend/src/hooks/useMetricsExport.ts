import { useMemo } from 'react'
import type { VCenter } from '../api/schemas'
import type { MetricPoint } from '../metrics/normalizeMetricSeriesResponse'
import type { MetricCsvExportOptions } from '../metrics/metricCsv'

type UseMetricsExportParams = {
  vcenterId: string
  vcenters: VCenter[]
  metricKey: string
  points: MetricPoint[]
  loading: boolean
  eventSeriesLoading: boolean
  chartEventType: string
  eventRateBuckets: { bucket_start: string; count: number }[] | null
  perfBucketSeconds: number
  countByEpochSec: Map<number, number>
}

export function useMetricsExport({
  vcenterId,
  vcenters,
  metricKey,
  points,
  loading,
  eventSeriesLoading,
  chartEventType,
  eventRateBuckets,
  perfBucketSeconds,
  countByEpochSec,
}: UseMetricsExportParams) {
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

  return {
    vcenterExportLabel,
    csvExportOptions,
    exportDisabled,
  }
}
