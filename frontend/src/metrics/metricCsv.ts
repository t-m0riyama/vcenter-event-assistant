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

export function metricPointsToCsv(points: MetricPoint[]): string {
  const lines: string[] = [HEADER.join(',')]
  for (const p of points) {
    lines.push(
      [
        escapeCsvField(p.sampled_at),
        String(p.value),
        escapeCsvField(p.entity_name),
        escapeCsvField(p.entity_moid),
        escapeCsvField(p.metric_key),
        escapeCsvField(p.vcenter_id),
      ].join(','),
    )
  }
  return `${lines.join('\r\n')}\r\n`
}

export function downloadMetricPointsCsv(points: MetricPoint[], filename: string): void {
  const csv = metricPointsToCsv(points)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.click()
  URL.revokeObjectURL(url)
}
