import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiGet } from '../api'
import { incidentTimelineManualSnapshotListItemSchema } from '../api/schemas'
import { TimeZoneProvider } from '../datetime/TimeZoneProvider'
import { ThemeProvider } from '../theme/ThemeProvider'
import { useMetricsPanelController, type MetricsSnapshotReplayInput } from './useMetricsPanelController'

vi.mock('../api', () => ({ apiGet: vi.fn() }))
const vcenterId = '00000000-0000-4000-8000-000000000001'
const item = incidentTimelineManualSnapshotListItemSchema.parse({
  snapshot_id: 'snapshot-1', operator_note: 'test',
  from: '2026-05-07T00:00:00Z', to: '2026-05-08T00:00:00Z',
  timestamp_utc: '2026-05-07T01:00:00Z',
  build_request_payload: { from: '2026-05-07T00:00:00Z', to: '2026-05-08T00:00:00Z' },
  graph_context: {
    vcenter_id: vcenterId, metric_key: 'host.memory_usage_pct', chart_event_type: 'VmPoweredOnEvent',
    captured_range: { from: '2026-05-07T02:00:00Z', to: '2026-05-07T03:00:00Z' },
  },
})
function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider><TimeZoneProvider>{children}</TimeZoneProvider></ThemeProvider>
}
const metricRequests = () => vi.mocked(apiGet).mock.calls
  .map(([url]) => url).filter(url => url.startsWith('/api/metrics?'))

beforeEach(() => {
  localStorage.setItem('vea.displayTimeZone', 'UTC')
  vi.mocked(apiGet).mockReset().mockImplementation(async path => {
    if (path.startsWith('/api/metrics/keys')) return { metric_keys: ['host.cpu_usage_pct', 'host.memory_usage_pct'] }
    if (path.startsWith('/api/metrics?')) return { items: [], total: 0 }
    if (path.startsWith('/api/events/event-types')) return { event_types: [] }
    return []
  })
})
afterEach(() => localStorage.removeItem('vea.displayTimeZone'))

describe('useMetricsPanelController', () => {
  it('selects the default metric and clears hidden legend selections when the metric changes', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useMetricsPanelController(onError, 300), { wrapper })
    await waitFor(() => expect(metricRequests().length).toBeGreaterThan(0))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.metricKeys).toContain(result.current.metricKey)
    act(() => result.current.onMetricsLegendClick({ dataKey: 'value' }))
    expect(result.current.hiddenSeriesDataKeys.has('value')).toBe(true)
    const selected = result.current.metricKey
    act(() => result.current.setMetricKey(selected === 'host.memory_usage_pct' ? 'host.cpu_usage_pct' : 'host.memory_usage_pct'))
    expect(result.current.hiddenSeriesDataKeys.size).toBe(0)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(onError).not.toHaveBeenCalledWith(expect.any(String))
  })

  it('replays saved selections and range, preserves edits on normal rerenders, and clears the marker on exit', async () => {
    const onError = vi.fn()
    const { result, rerender } = renderHook(
      ({ replay }: { replay: MetricsSnapshotReplayInput | null }) => useMetricsPanelController(onError, 300, replay),
      { wrapper, initialProps: { replay: { item, nonce: 1 } } },
    )
    await waitFor(() => expect(metricRequests().length).toBeGreaterThan(0))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.vcenterId).toBe(vcenterId)
    expect(result.current.metricKey).toBe('host.memory_usage_pct')
    expect(result.current.chartEventType).toBe('VmPoweredOnEvent')
    expect(result.current.snapshotChartGuidelineMs).toBe(Date.parse(item.timestamp_utc))
    expect(result.current.rangeParts.fromTime).toBe('02:00')
    const request = new URL(metricRequests().at(-1)!, 'http://test')
    expect(request.searchParams.get('vcenter_id')).toBe(vcenterId)
    expect(request.searchParams.get('metric_key')).toBe('host.memory_usage_pct')
    expect(Date.parse(request.searchParams.get('from')!)).toBe(Date.parse('2026-05-07T02:00:00Z'))
    const resetKey = result.current.chartResetKey
    act(() => result.current.setChartEventType('edited'))
    rerender({ replay: { item, nonce: 1 } })
    expect(result.current.chartEventType).toBe('edited')
    expect(result.current.chartResetKey).toBe(resetKey)
    const before = metricRequests().length
    rerender({ replay: { item, nonce: 2 } })
    await waitFor(() => expect(metricRequests().length).toBeGreaterThan(before))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.chartEventType).toBe('VmPoweredOnEvent')
    expect(result.current.chartResetKey).toBe(resetKey + 1)
    rerender({ replay: null })
    expect(result.current.snapshotChartGuidelineMs).toBeNull()
    expect(result.current.metricKey).toBe('host.memory_usage_pct')
    expect(onError).not.toHaveBeenCalledWith(expect.any(String))
  })
})
