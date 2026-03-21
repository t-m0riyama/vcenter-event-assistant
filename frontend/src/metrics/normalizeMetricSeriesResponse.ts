import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'

export type MetricPoint = {
  sampled_at: string
  value: number
  entity_name: string
  entity_moid: string
  metric_key: string
  vcenter_id: string
}

export type MetricSeriesResponse = {
  points: MetricPoint[]
  total: number
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.trim() !== ''
}

function isValidMetricPoint(x: unknown): x is MetricPoint {
  if (!x || typeof x !== 'object') return false
  const p = x as Record<string, unknown>
  const value = p.value
  if (typeof value !== 'number' || !Number.isFinite(value)) return false
  const sampledAt = p.sampled_at
  if (!isNonEmptyString(sampledAt)) return false
  if (Number.isNaN(parseApiUtcInstantMs(sampledAt))) return false
  if (typeof p.entity_name !== 'string') return false
  if (typeof p.entity_moid !== 'string') return false
  if (typeof p.metric_key !== 'string') return false
  if (typeof p.vcenter_id !== 'string') return false
  return true
}

export function normalizeMetricSeriesResponse(data: unknown): MetricSeriesResponse {
  if (!data || typeof data !== 'object') {
    return { points: [], total: 0 }
  }
  const o = data as Record<string, unknown>
  const rawPoints = o.points
  const points = Array.isArray(rawPoints)
    ? rawPoints.filter(isValidMetricPoint).map((p) => ({
        sampled_at: p.sampled_at,
        value: p.value,
        entity_name: p.entity_name,
        entity_moid: p.entity_moid,
        metric_key: p.metric_key,
        vcenter_id: p.vcenter_id,
      }))
    : []
  const totalRaw = o.total
  const total = typeof totalRaw === 'number' && Number.isFinite(totalRaw) ? totalRaw : 0
  return { points, total }
}
