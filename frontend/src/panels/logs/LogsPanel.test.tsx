/** @vitest-environment happy-dom */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LogsPanel } from './LogsPanel'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'

const row = {
  id: 1, vcenter_id: 'vc-1', source_id: 'esxi-1', host: 'esxi.local', log_kind: 'vmkernel',
  file_generation: 'gen-1', byte_offset: 12, occurred_at: null,
  collected_at: '2026-10-02T10:00:00Z', effective_at: '2026-10-02T10:00:00Z', severity: 'error', message: 'Storage error\n stack trace',
}
const response = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200 }))

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

describe('LogsPanel', () => {
  it('keeps saved log search usable when the latest collection failed', async () => {
    const onError = vi.fn()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'vcenter8-01' }])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [{
        id: 'vea.remote.logs', display_name: 'VEA Remote Logs', source: 'external', status: 'enabled',
        error: null, version: '0.2.0', api_version: 1, data_kinds: ['log'], interval_seconds: 60, timeout_seconds: 45,
        runs: [{ vcenter_id: 'vc-1', vcenter_name: 'vcenter8-01', status: 'failed', collector_version: '0.2.0',
          last_started_at: null, last_success_at: null, last_failure_at: '2026-10-03T00:00:00Z',
          events_inserted: 0, metrics_inserted: 0, logs_inserted: 0, error: 'ValueError: collector execution failed' }],
      }] })
      return response({ items: [row], total: 1 })
    }))
    render(<TimeZoneProvider><LogsPanel onError={onError} /></TimeZoneProvider>)
    await waitFor(() => expect(screen.getByText('Storage error')).toBeInTheDocument())
    expect(screen.getByLabelText('ログ収集状況')).toHaveTextContent('保存済みログの検索は引き続き利用できます')
    expect(screen.getByText(/vcenter8-01: ValueError/)).toBeInTheDocument()
    expect(screen.getByText(/期間を広げても、サーバーの過去ログを追加取得/)).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalledWith(expect.any(String))
  })

  it('searches the linked range, displays raw text and unparsed time, and links back to events', async () => {
    window.history.replaceState(null, '', '#/logs?vcenter_id=vc-1&from=2026-10-02T09%3A55%3A25Z&to=2026-10-02T10%3A05%3A25Z')
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
      return response({ items: [row], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    await waitFor(() => expect(screen.getByText('Storage error')).toBeInTheDocument())
    expect(screen.getByText('発生時刻未解析（取得時刻）')).toBeInTheDocument()
    expect(screen.getByText('Storage error stack trace', { exact: false, selector: 'pre' })).toBeInTheDocument()
    const url = new URL(String(fetchMock.mock.calls.find(([input]) => String(input).startsWith('/api/logs'))![0]), 'http://test')
    expect(url.searchParams.get('from')).toBe('2026-10-02T09:55:25Z')
    expect(url.searchParams.get('vcenter_id')).toBe('vc-1')
    expect(screen.getByText('同じ期間のイベント').getAttribute('href')).toContain('#/events?')
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('message_contains=Storage'))).toBe(true))
  })
})
