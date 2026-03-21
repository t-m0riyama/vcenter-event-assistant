import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import type { MetricPoint } from './normalizeMetricSeriesResponse'

export function escapeCsvField(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

const HEADER = [
  'sampled_at',
  'value',
  'entity_name',
  'entity_moid',
  'metric_key',
  'vcenter_id',
] as const

const OVERLAY_HEADER = [
  'event_type_overlay',
  'bucket_epoch_utc_sec',
  'event_count_in_bucket',
] as const

/** Aligns with server `GET /api/events/rate-series` bucketing. */
export function bucketEpochUtcSec(iso: string, bucketSeconds: number): number {
  const sec = Math.floor(parseApiUtcInstantMs(iso) / 1000)
  return Math.floor(sec / bucketSeconds) * bucketSeconds
}

export type MetricCsvExportOptions = {
  bucketSeconds?: number
  eventCountByBucketEpochSec?: Map<number, number>
  overlayEventType?: string
}

export function metricPointsToCsv(points: MetricPoint[], options?: MetricCsvExportOptions): string {
  const overlay =
    options?.overlayEventType?.trim() &&
    options.bucketSeconds != null &&
    options.eventCountByBucketEpochSec != null
  const header = overlay ? [...HEADER, ...OVERLAY_HEADER] : [...HEADER]
  const lines: string[] = [header.join(',')]
  const b = options?.bucketSeconds ?? 300
  const map = options?.eventCountByBucketEpochSec
  const et = options?.overlayEventType?.trim() ?? ''
  for (const p of points) {
    const base = [
      escapeCsvField(p.sampled_at),
      String(p.value),
      escapeCsvField(p.entity_name),
      escapeCsvField(p.entity_moid),
      escapeCsvField(p.metric_key),
      escapeCsvField(p.vcenter_id),
    ]
    if (overlay && map) {
      const be = bucketEpochUtcSec(p.sampled_at, b)
      base.push(
        escapeCsvField(et),
        String(be),
        String(map.get(be) ?? 0),
      )
    }
    lines.push(base.join(','))
  }
  return `${lines.join('\r\n')}\r\n`
}

export function downloadMetricPointsCsv(
  points: MetricPoint[],
  filename: string,
  options?: MetricCsvExportOptions,
): void {
  const csv = metricPointsToCsv(points, options)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.click()
  URL.revokeObjectURL(url)
}
