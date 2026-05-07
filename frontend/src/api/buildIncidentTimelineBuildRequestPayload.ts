import type { IncidentTimelineBuildRequest } from './schemas'

type ResolvedRange = {
  from: string
  to: string
}

type IncidentTimelineContextOptions = {
  vcenterId: string
  includePeriodMetricsCpu: boolean
  includePeriodMetricsMemory: boolean
  includePeriodMetricsDiskIo: boolean
  includePeriodMetricsNetworkIo: boolean
  metricThresholdCpuPct: number | null | undefined
  metricThresholdMemoryPct: number | null | undefined
  metricThresholdDiskPct: number | null | undefined
  metricThresholdNetworkPct: number | null | undefined
  alertTopN?: number
}

/**
 * チャット/タイムライン共通で使う、期間コンテキスト用 POST 本文を組み立てる。
 */
export function buildIncidentTimelineBuildRequestPayload(params: {
  resolvedRange: ResolvedRange
  options: IncidentTimelineContextOptions
}): IncidentTimelineBuildRequest {
  const { resolvedRange, options } = params

  const payload: IncidentTimelineBuildRequest = {
    from: resolvedRange.from,
    to: resolvedRange.to,
    include_period_metrics_cpu: options.includePeriodMetricsCpu,
    include_period_metrics_memory: options.includePeriodMetricsMemory,
    include_period_metrics_disk_io: options.includePeriodMetricsDiskIo,
    include_period_metrics_network_io: options.includePeriodMetricsNetworkIo,
    metric_threshold_cpu_pct: options.metricThresholdCpuPct,
    metric_threshold_memory_pct: options.metricThresholdMemoryPct,
    metric_threshold_disk_pct: options.metricThresholdDiskPct,
    metric_threshold_network_pct: options.metricThresholdNetworkPct,
  }
  if (options.vcenterId) {
    payload.vcenter_id = options.vcenterId
  }
  if (typeof options.alertTopN === 'number') {
    payload.alert_top_n = options.alertTopN
  }
  return payload
}
