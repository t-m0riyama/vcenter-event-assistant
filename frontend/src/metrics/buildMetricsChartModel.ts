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
 * `datastore.*` メトリクスキーかどうか（データストア単位の系列に分割する）。
 */
export function isDatastoreMetricKey(metricKey: string): boolean {
  return metricKey.trim().startsWith('datastore.')
}

function isEntitySplitMetricKey(metricKey: string): boolean {
  return isHostMetricKey(metricKey) || isDatastoreMetricKey(metricKey)
}

/**
 * Recharts の `dataKey` 用に `entity_moid`（ホスト MOID・データストア MOID 共通）を列名として使える形にする。
 */
export function hostMetricSeriesDataKey(entityMoid: string, vcenterId?: string): string {
  const s = String(entityMoid).trim()
  if (!s) return 'm_unknown'
  const safe = s.replace(/[^a-zA-Z0-9_]/g, '_')
  const base = `m_${safe}`
  if (!vcenterId) return base
  const safeVc = String(vcenterId).replace(/[^a-zA-Z0-9_]/g, '_')
  return `${base}__vc_${safeVc}`
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
  /** Recharts `Line` の `name`（凡例）のエンティティ部分 */
  legendName: string
  /** 複数 vCenter 集約時のみ。凡例の vCenter 接頭辞。 */
  vcenterLegendPrefix?: string
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

function buildLegendNamesByMoid(points: MetricPoint[], multiVcenter: boolean): Map<string, string> {
  const seriesKey = (p: MetricPoint) =>
    multiVcenter ? `${p.vcenter_id}\0${p.entity_moid}` : String(p.entity_moid)

  const nameBySeriesKey = new Map<string, string>()
  for (const p of points) {
    const k = seriesKey(p)
    if (!nameBySeriesKey.has(k)) {
      const n = String(p.entity_name ?? '').trim()
      nameBySeriesKey.set(k, n || String(p.entity_moid))
    }
  }
  const moidsByDisplayScope = new Map<string, Set<string>>()
  for (const p of points) {
    const k = seriesKey(p)
    const name = nameBySeriesKey.get(k) ?? String(p.entity_moid)
    const scope = multiVcenter ? `${p.vcenter_id}\0${name}` : name
    if (!moidsByDisplayScope.has(scope)) moidsByDisplayScope.set(scope, new Set())
    moidsByDisplayScope.get(scope)!.add(String(p.entity_moid))
  }
  const out = new Map<string, string>()
  for (const p of points) {
    const k = seriesKey(p)
    if (out.has(k)) continue
    const name = nameBySeriesKey.get(k) ?? String(p.entity_moid)
    const scope = multiVcenter ? `${p.vcenter_id}\0${name}` : name
    const dup = (moidsByDisplayScope.get(scope)?.size ?? 0) > 1
    out.set(k, dup ? `${name} (${p.entity_moid})` : name)
  }
  return out
}

function distinctVcenterIds(points: MetricPoint[]): string[] {
  return [...new Set(points.map((p) => String(p.vcenter_id)))].sort()
}

/** 凡例・ツールチップ用の系列表示名を組み立てる。 */
export function formatMetricChartSeriesLegendName(
  series: MetricChartSeriesLine,
  vcenterLabelForChart: string,
): string {
  const entity = series.legendName
  if (series.vcenterLegendPrefix) {
    return `${series.vcenterLegendPrefix} / ${entity}`
  }
  return `${vcenterLabelForChart} / ${entity}`
}

/**
 * メトリクスグラフ用の行データと左軸系列メタデータを組み立てる。
 * `host.*` または `datastore.*` のときは `entity_moid` ごとに列を分け、同一時刻を 1 行にマージする。
 * `splitSeriesByVcenter` が true（vCenter「全て」選択時）のときは `vcenter_id` も系列キーに含める。
 */
export function buildMetricsChartModel(
  metricKey: string,
  points: MetricPoint[],
  perfBucketSeconds: number,
  showEventLine: boolean,
  countByEpochSec: ReadonlyMap<number, number>,
  vcenterNameById?: ReadonlyMap<string, string>,
  splitSeriesByVcenter = false,
): BuildMetricsChartModelResult {
  const valid = filterValidPoints(points)
  if (!isEntitySplitMetricKey(metricKey)) {
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

  const splitByVcenter = splitSeriesByVcenter || distinctVcenterIds(valid).length > 1
  const legendBySeriesKey = buildLegendNamesByMoid(valid, splitByVcenter)
  const seriesIdentities = [
    ...new Map(
      valid.map((p) => {
        const moid = String(p.entity_moid)
        const vcenterId = String(p.vcenter_id)
        const identityKey = splitByVcenter ? `${vcenterId}\0${moid}` : moid
        return [identityKey, { vcenterId, moid }] as const
      }),
    ).values(),
  ].sort((a, b) => {
    const byVc = a.vcenterId.localeCompare(b.vcenterId)
    if (byVc !== 0) return byVc
    return a.moid.localeCompare(b.moid)
  })

  const metricSeries: MetricChartSeriesLine[] = seriesIdentities.map(({ vcenterId, moid }) => {
    const seriesKey = splitByVcenter ? `${vcenterId}\0${moid}` : moid
    const vcenterLegendPrefix = splitByVcenter
      ? (vcenterNameById?.get(vcenterId) ?? vcenterId)
      : undefined
    return {
      dataKey: hostMetricSeriesDataKey(moid, splitByVcenter ? vcenterId : undefined),
      legendName: legendBySeriesKey.get(seriesKey) ?? moid,
      vcenterLegendPrefix,
    }
  })

  const byTime = new Map<number, MetricChartRowHost>()
  for (const p of valid) {
    const sampled = String(p.sampled_at)
    const tMs = parseApiUtcInstantMs(sampled)
    const key = hostMetricSeriesDataKey(
      String(p.entity_moid),
      splitByVcenter ? String(p.vcenter_id) : undefined,
    )
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
