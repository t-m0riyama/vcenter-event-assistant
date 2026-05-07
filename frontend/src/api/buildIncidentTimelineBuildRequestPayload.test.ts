import { describe, expect, it } from 'vitest'

import { buildIncidentTimelineBuildRequestPayload } from './buildIncidentTimelineBuildRequestPayload'

describe('buildIncidentTimelineBuildRequestPayload', () => {
  it('期待される期間コンテキスト項目を含む', () => {
    const payload = buildIncidentTimelineBuildRequestPayload({
      resolvedRange: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      options: {
        vcenterId: '550e8400-e29b-41d4-a716-446655440000',
        includePeriodMetricsCpu: true,
        includePeriodMetricsMemory: false,
        includePeriodMetricsDiskIo: true,
        includePeriodMetricsNetworkIo: false,
        metricThresholdCpuPct: 80,
        metricThresholdMemoryPct: 85,
        metricThresholdDiskPct: 75,
        metricThresholdNetworkPct: 70,
      },
    })

    expect(payload).toEqual({
      from: '2026-05-07T00:00:00Z',
      to: '2026-05-08T00:00:00Z',
      vcenter_id: '550e8400-e29b-41d4-a716-446655440000',
      include_period_metrics_cpu: true,
      include_period_metrics_memory: false,
      include_period_metrics_disk_io: true,
      include_period_metrics_network_io: false,
      metric_threshold_cpu_pct: 80,
      metric_threshold_memory_pct: 85,
      metric_threshold_disk_pct: 75,
      metric_threshold_network_pct: 70,
    })
  })

  it('vcenterId が空文字のとき vcenter_id を含めない', () => {
    const payload = buildIncidentTimelineBuildRequestPayload({
      resolvedRange: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      options: {
        vcenterId: '',
        includePeriodMetricsCpu: false,
        includePeriodMetricsMemory: false,
        includePeriodMetricsDiskIo: false,
        includePeriodMetricsNetworkIo: false,
        metricThresholdCpuPct: 80,
        metricThresholdMemoryPct: 85,
        metricThresholdDiskPct: 75,
        metricThresholdNetworkPct: 75,
      },
    })

    expect(payload).not.toHaveProperty('vcenter_id')
  })

  it('閾値の null / undefined をそのまま保持する', () => {
    const payload = buildIncidentTimelineBuildRequestPayload({
      resolvedRange: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      options: {
        vcenterId: '550e8400-e29b-41d4-a716-446655440000',
        includePeriodMetricsCpu: true,
        includePeriodMetricsMemory: true,
        includePeriodMetricsDiskIo: true,
        includePeriodMetricsNetworkIo: true,
        metricThresholdCpuPct: null,
        metricThresholdMemoryPct: undefined,
        metricThresholdDiskPct: 0,
        metricThresholdNetworkPct: 100,
      },
    })

    expect(payload.metric_threshold_cpu_pct).toBeNull()
    expect(payload).toHaveProperty('metric_threshold_memory_pct', undefined)
    expect(payload.metric_threshold_disk_pct).toBe(0)
    expect(payload.metric_threshold_network_pct).toBe(100)
  })

  it('alertTopN が指定されたら alert_top_n を本文に含める', () => {
    const payload = buildIncidentTimelineBuildRequestPayload({
      resolvedRange: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      options: {
        vcenterId: '550e8400-e29b-41d4-a716-446655440000',
        includePeriodMetricsCpu: false,
        includePeriodMetricsMemory: false,
        includePeriodMetricsDiskIo: false,
        includePeriodMetricsNetworkIo: false,
        metricThresholdCpuPct: null,
        metricThresholdMemoryPct: null,
        metricThresholdDiskPct: null,
        metricThresholdNetworkPct: null,
        alertTopN: 7,
      },
    })

    expect(payload.alert_top_n).toBe(7)
  })

  it('alertTopN が未指定なら alert_top_n を本文に含めない', () => {
    const payload = buildIncidentTimelineBuildRequestPayload({
      resolvedRange: {
        from: '2026-05-07T00:00:00Z',
        to: '2026-05-08T00:00:00Z',
      },
      options: {
        vcenterId: '',
        includePeriodMetricsCpu: false,
        includePeriodMetricsMemory: false,
        includePeriodMetricsDiskIo: false,
        includePeriodMetricsNetworkIo: false,
        metricThresholdCpuPct: null,
        metricThresholdMemoryPct: null,
        metricThresholdDiskPct: null,
        metricThresholdNetworkPct: null,
      },
    })

    expect(payload).not.toHaveProperty('alert_top_n')
  })
})
