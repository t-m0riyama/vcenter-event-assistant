/**
 * Metric keys the backend collector can emit (including quickStats + PerformanceManager + Datastore).
 * Merged with {@link GET /api/metrics/keys} so the graph tab can target series before the first sample exists.
 */
export const KNOWN_METRIC_KEYS: readonly string[] = [
  'datastore.space.used_bytes',
  'datastore.space.used_pct',
  'host.cpu.usage_pct',
  'host.disk.read_kbps',
  'host.disk.usage_pct',
  'host.disk.write_kbps',
  'host.mem.usage_pct',
  'host.net.bytes_rx_kbps',
  'host.net.bytes_tx_kbps',
  'host.net.dropped_rx_total',
  'host.net.dropped_tx_total',
  'host.net.errors_rx_total',
  'host.net.errors_tx_total',
  'host.net.usage_kbps',
]

export type MetricCatalogDefinition = {
  collector_id: string
  key: string
  display_name: string
  unit: string
  entity_type: string
  series_mode: 'entity' | 'single'
  category: string
  description: string
}

let runtimeCatalog = new Map<string, MetricCatalogDefinition>()

export function installMetricCatalog(definitions: readonly MetricCatalogDefinition[]): void {
  runtimeCatalog = new Map(definitions.map((definition) => [definition.key, definition]))
}

export function metricSeriesMode(metricKey: string): 'entity' | 'single' {
  const configured = runtimeCatalog.get(metricKey.trim())?.series_mode
  if (configured) return configured
  return metricKey.trim().startsWith('host.') || metricKey.trim().startsWith('datastore.')
    ? 'entity'
    : 'single'
}

/**
 * Returns sorted unique keys: catalog plus anything already stored for the vCenter.
 */
export function mergeMetricKeyOptions(apiKeys: readonly string[]): string[] {
  const set = new Set<string>([...KNOWN_METRIC_KEYS, ...runtimeCatalog.keys(), ...apiKeys])
  return [...set].sort((a, b) => a.localeCompare(b))
}
