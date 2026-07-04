/** 期間メトリクス閾値（Chat / Timeline 共通の既定値） */

export const DEFAULT_METRIC_THRESHOLD_CPU_PCT = 80
/** メモリ使用率の既定閾値（%）。 */
export const DEFAULT_METRIC_THRESHOLD_MEMORY_PCT = 85
/** ディスク使用率の既定閾値（%）。 */
export const DEFAULT_METRIC_THRESHOLD_DISK_PCT = 75
/** ネットワーク使用率の既定閾値（%）。 */
export const DEFAULT_METRIC_THRESHOLD_NETWORK_PCT = 75

/** 0..100 の有限数か（期間メトリクス閾値入力の妥当性）。 */
export function isValidMetricThresholdPercent(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 100
}
