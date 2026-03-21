export type MetricPoint = {
  sampled_at: string
  value: number
  entity_name: string
  metric_key: string
  vcenter_id: string
}

export type MetricSeriesResponse = {
  points: MetricPoint[]
  total: number
}

export function normalizeMetricSeriesResponse(data: unknown): MetricSeriesResponse {
  if (!data || typeof data !== 'object') {
    return { points: [], total: 0 }
  }
  const o = data as Record<string, unknown>
  const rawPoints = o.points
  const points = Array.isArray(rawPoints) ? (rawPoints as MetricPoint[]) : []
  const totalRaw = o.total
  const total = typeof totalRaw === 'number' && Number.isFinite(totalRaw) ? totalRaw : 0
  return { points, total }
}
