import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import type { MetricsGraphRangeResolve } from '../datetime/graphRange'
import type { MetricPoint } from './normalizeMetricSeriesResponse'

/**
 * メトリクス点または明示期間から、イベントレート API 用の from/to を導出する。
 */
export function computeEventRateOverlayRange(
  graphRange: MetricsGraphRangeResolve,
  points: MetricPoint[],
  perfBucketSeconds: number,
): { from: string; to: string } | null {
  let from: string
  let to: string
  if (graphRange.mode === 'range') {
    from = graphRange.from
    to = graphRange.to
  } else if (graphRange.mode === 'none') {
    let minTs = Infinity
    let maxTs = -Infinity
    for (const p of points) {
      const t = parseApiUtcInstantMs(p.sampled_at)
      if (Number.isFinite(t)) {
        if (t < minTs) minTs = t
        if (t > maxTs) maxTs = t
      }
    }
    if (!Number.isFinite(minTs) || !Number.isFinite(maxTs)) {
      return null
    }
    from = new Date(minTs).toISOString()
    to = new Date(maxTs).toISOString()
  } else {
    return null
  }

  const fromMs = parseApiUtcInstantMs(from)
  const toMs = parseApiUtcInstantMs(to)
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
    return null
  }
  if (fromMs >= toMs) {
    to = new Date(fromMs + Math.max(perfBucketSeconds, 60) * 1000).toISOString()
  }
  return { from, to }
}
