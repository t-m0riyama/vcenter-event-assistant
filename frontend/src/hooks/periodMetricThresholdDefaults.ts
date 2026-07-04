/** 期間メトリクス閾値（Chat / Timeline 共通の既定値） */

export const DEFAULT_METRIC_THRESHOLD_CPU_PCT = 80
export const DEFAULT_METRIC_THRESHOLD_MEMORY_PCT = 85
export const DEFAULT_METRIC_THRESHOLD_DISK_PCT = 75
export const DEFAULT_METRIC_THRESHOLD_NETWORK_PCT = 75

export function isValidMetricThresholdPercent(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 100
}
