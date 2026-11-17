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
}

/**
 * チャット/タイムライン共通で使う、期間コンテキスト用 POST 本文を組み立てる。
 *
 * ディスクとネットワークの閾値（`metric_threshold_disk_pct` / `metric_threshold_network_pct`）は送らない。
 * 値が KB/s の指標に % の閾値は当てられず、サーバも使わない（Issue #316）。
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
  }
  if (options.vcenterId) {
    payload.vcenter_id = options.vcenterId
  }
  return payload
}
