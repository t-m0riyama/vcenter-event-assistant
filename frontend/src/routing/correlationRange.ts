export type CorrelationRange = { vcenterId: string; from: string; to: string; patternKey?: string }

export function readCorrelationRange(tab: 'logs' | 'events'): CorrelationRange | null {
  const [path, query] = window.location.hash.split('?', 2)
  if (path !== `#/${tab}`) return null
  const params = new URLSearchParams(query)
  const vcenterId = params.get('vcenter_id') ?? ''
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  if (!vcenterId || !Number.isFinite(Date.parse(from)) || !Number.isFinite(Date.parse(to)) || Date.parse(from) > Date.parse(to)) return null
  const patternKey = tab === 'logs' ? params.get('pattern_key') : null
  return patternKey ? { vcenterId, from, to, patternKey } : { vcenterId, from, to }
}

export function correlationHash(tab: 'logs' | 'events', range: CorrelationRange): string {
  const params = new URLSearchParams({ vcenter_id: range.vcenterId, from: range.from, to: range.to })
  if (tab === 'logs' && range.patternKey) params.set('pattern_key', range.patternKey)
  return `#/${tab}?${params}`
}

export function logsAroundEvent(vcenterId: string, occurredAt: string): string {
  const time = Date.parse(occurredAt)
  return correlationHash('logs', {
    vcenterId, from: new Date(time - 300_000).toISOString(), to: new Date(time + 300_000).toISOString(),
  })
}
