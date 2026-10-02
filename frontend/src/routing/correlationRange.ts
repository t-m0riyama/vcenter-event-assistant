export type CorrelationRange = { vcenterId: string; from: string; to: string }

export function readCorrelationRange(tab: 'logs' | 'events'): CorrelationRange | null {
  const [path, query] = window.location.hash.split('?', 2)
  if (path !== `#/${tab}`) return null
  const params = new URLSearchParams(query)
  const vcenterId = params.get('vcenter_id') ?? ''
  const from = params.get('from') ?? ''
  const to = params.get('to') ?? ''
  if (!vcenterId || !Number.isFinite(Date.parse(from)) || !Number.isFinite(Date.parse(to)) || Date.parse(from) > Date.parse(to)) return null
  return { vcenterId, from, to }
}

export function correlationHash(tab: 'logs' | 'events', range: CorrelationRange): string {
  return `#/${tab}?${new URLSearchParams({ vcenter_id: range.vcenterId, from: range.from, to: range.to })}`
}

export function logsAroundEvent(vcenterId: string, occurredAt: string): string {
  const time = Date.parse(occurredAt)
  return correlationHash('logs', {
    vcenterId, from: new Date(time - 300_000).toISOString(), to: new Date(time + 300_000).toISOString(),
  })
}
