import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import type { MetricPoint } from './normalizeMetricSeriesResponse'
import { bucketEpochUtcSec } from './metricCsv'

/**
 * `host.*` メトリクスキーかどうか（ESXi ホスト単位の系列に分割する）。
 */
export function isHostMetricKey(metricKey: string): boolean {
  return metricKey.trim().startsWith('host.')
}

/**
 * Recharts の `dataKey` 用に `entity_moid` を列名として使える形にする。
 */
export function hostMetricSeriesDataKey(entityMoid: string): string {
  const s = String(entityMoid).trim()
  if (!s) return 'm_unknown'
  const safe = s.replace(/[^a-zA-Z0-9_]/g, '_')
  return `m_${safe}`
}

export type MetricChartRowSingle = {
  tMs: number
  v: number
  evCount: number
}

export type MetricChartRowHost = {
  tMs: number
  evCount: number
  [seriesDataKey: string]: number | undefined | null
}

export type MetricChartSeriesLine = {
  dataKey: string
  /** Recharts `Line` の `name`（凡例） */
  legendName: string
}

export type BuildMetricsChartModelResult =
  | {
      mode: 'single'
      rows: MetricChartRowSingle[]
      metricSeries: [MetricChartSeriesLine & { dataKey: 'v' }]
    }
  | {
      mode: 'host'
      rows: MetricChartRowHost[]
      metricSeries: MetricChartSeriesLine[]
    }

function filterValidPoints(points: MetricPoint[]): MetricPoint[] {
  return points.filter((p) => {
    if (p == null || !Number.isFinite(p.value)) return false
    return Number.isFinite(parseApiUtcInstantMs(String(p.sampled_at)))
  })
}

function buildLegendNamesByMoid(points: MetricPoint[]): Map<string, string> {
  const nameByMoid = new Map<string, string>()
  for (const p of points) {
    const m = String(p.entity_moid)
    if (!nameByMoid.has(m)) {
      const n = String(p.entity_name ?? '').trim()
      nameByMoid.set(m, n || m)
    }
  }
  const moidsByDisplayName = new Map<string, Set<string>>()
  for (const [moid, name] of nameByMoid) {
    if (!moidsByDisplayName.has(name)) moidsByDisplayName.set(name, new Set())
    moidsByDisplayName.get(name)!.add(moid)
  }
  const out = new Map<string, string>()
  for (const [moid, name] of nameByMoid) {
    const dup = (moidsByDisplayName.get(name)?.size ?? 0) > 1
    out.set(moid, dup ? `${name} (${moid})` : name)
  }
  return out
}

/**
 * メトリクスグラフ用の行データと左軸系列メタデータを組み立てる。
 * `host.*` のときはホスト（`entity_moid`）ごとに列を分ける。
 */
export function buildMetricsChartModel(
  metricKey: string,
  points: MetricPoint[],
  perfBucketSeconds: number,
  showEventLine: boolean,
  countByEpochSec: ReadonlyMap<number, number>,
): BuildMetricsChartModelResult {
  const valid = filterValidPoints(points)
  if (!isHostMetricKey(metricKey)) {
    const rows: MetricChartRowSingle[] = valid.map((p) => {
      const sampled = String(p.sampled_at)
      const tMs = parseApiUtcInstantMs(sampled)
      const bucketSec = bucketEpochUtcSec(sampled, perfBucketSeconds)
      const evCount = showEventLine ? (countByEpochSec.get(bucketSec) ?? 0) : 0
      return { tMs, v: p.value, evCount }
    })
    return {
      mode: 'single',
      rows,
      metricSeries: [{ dataKey: 'v', legendName: '' }],
    }
  }

  const legendByMoid = buildLegendNamesByMoid(valid)
  const moids = [...new Set(valid.map((p) => String(p.entity_moid)))].sort()
  const metricSeries: MetricChartSeriesLine[] = moids.map((moid) => ({
    dataKey: hostMetricSeriesDataKey(moid),
    legendName: legendByMoid.get(moid) ?? moid,
  }))

  const byTime = new Map<number, MetricChartRowHost>()
  for (const p of valid) {
    const sampled = String(p.sampled_at)
    const tMs = parseApiUtcInstantMs(sampled)
    const key = hostMetricSeriesDataKey(String(p.entity_moid))
    const bucketSec = bucketEpochUtcSec(sampled, perfBucketSeconds)
    const evCount = showEventLine ? (countByEpochSec.get(bucketSec) ?? 0) : 0
    let row = byTime.get(tMs)
    if (!row) {
      row = { tMs, evCount }
      byTime.set(tMs, row)
    }
    row[key] = p.value
    row.evCount = evCount
  }

  const rows = [...byTime.keys()]
    .sort((a, b) => a - b)
    .map((tMs) => byTime.get(tMs)!)

  return { mode: 'host', rows, metricSeries }
}
