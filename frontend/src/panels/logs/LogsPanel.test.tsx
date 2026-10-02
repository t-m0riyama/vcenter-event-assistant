/** @vitest-environment happy-dom */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LogsPanel } from './LogsPanel'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'

const row = {
  id: 1, vcenter_id: 'vc-1', source_id: 'esxi-1', host: 'esxi.local', log_kind: 'vmkernel',
  file_generation: 'gen-1', byte_offset: 12, occurred_at: null,
  collected_at: '2026-10-02T10:00:00Z', effective_at: '2026-10-02T10:00:00Z', severity: 'error', message: 'Storage error\n stack trace',
}
const response = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200 }))

afterEach(() => { localStorage.removeItem('vea.displayTimeZone'); vi.useRealTimers(); vi.unstubAllGlobals(); window.history.replaceState(null, '', '/') })

function collectorResponse(status: 'failed' | 'ok') {
  return response({ generation: 1, collectors: [{
    id: 'vea.remote.logs', display_name: 'VEA Remote Logs', source: 'external', status: 'enabled',
    error: null, version: '0.2.0', api_version: 1, data_kinds: ['log'], interval_seconds: 60, timeout_seconds: 45,
    runs: [{ vcenter_id: 'vc-1', vcenter_name: 'vcenter8-01', status, collector_version: '0.2.0',
      last_started_at: null, last_success_at: null, last_failure_at: null,
      events_inserted: 0, metrics_inserted: 0, logs_inserted: 0,
      error: status === 'failed' ? 'worker exited before responding: collector execution failed' : null,
    }],
  }] })
}

describe('LogsPanel', () => {
  it('clears recovered collection errors on polling without reloading log pages and stops on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let status: 'failed' | 'ok' = 'failed'
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([])
      if (url.includes('/api/plugins')) return collectorResponse(status)
      return response({ items: [row], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    await screen.findByText(/worker exited before responding/)
    await screen.findByText('Storage error')
    const logRequests = () => fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/logs')).length
    const before = logRequests()
    status = 'ok'
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(screen.queryByLabelText('ログ収集状況')).not.toBeInTheDocument()
    expect(logRequests()).toBe(before)
    const total = fetchMock.mock.calls.length
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    fireEvent(window, new Event('focus'))
    expect(fetchMock.mock.calls).toHaveLength(total)
  })

  it('refreshes collection errors on focus and keeps saved logs usable when status fetching fails', async () => {
    let fail = true
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([])
      if (url.includes('/api/plugins')) return fail ? Promise.reject(new Error('offline')) : collectorResponse('ok')
      return response({ items: [row], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    await screen.findByText('Storage error')
    await screen.findByText('収集状況を更新できません: offline')
    expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeEnabled()
    fail = false
    fireEvent(window, new Event('focus'))
    await waitFor(() => expect(screen.queryByLabelText('ログ収集状況')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/logs'))).toHaveLength(1)
  })

  it('pauses collection status requests on another tab and refreshes when returning', async () => {
    let status: 'failed' | 'ok' = 'failed'
    const onError = vi.fn()
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([])
      if (url.includes('/api/plugins')) return collectorResponse(status)
      return response({ items: [row], total: 1 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const { rerender } = render(<TimeZoneProvider><LogsPanel onError={onError} active /></TimeZoneProvider>)
    await screen.findByText(/worker exited before responding/)
    rerender(<TimeZoneProvider><LogsPanel onError={onError} active={false} /></TimeZoneProvider>)
    const before = fetchMock.mock.calls.length
    fireEvent(window, new Event('focus'))
    expect(fetchMock.mock.calls).toHaveLength(before)
    status = 'ok'
    rerender(<TimeZoneProvider><LogsPanel onError={onError} active /></TimeZoneProvider>)
    await waitFor(() => expect(screen.queryByLabelText('ログ収集状況')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/logs'))).toHaveLength(1)
  })

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
    expect(screen.getByLabelText('ログ収集状況').closest('details')).toBeNull()
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
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).includes('message_contains=Storage'))).toBe(true))
  })

  it('summarizes collapsed filters and resets pagination when filters or the range change', async () => {
    localStorage.setItem('vea.displayTimeZone', 'UTC')
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
      return response({ items: [row], total: 101 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    await waitFor(() => expect(screen.getByText('全 101 件中 1–50 件を表示')).toBeInTheDocument())
    const summary = screen.getByText('絞り込み条件').closest('summary')!
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(summary).toHaveTextContent('開始指定なし ～ 終了指定なし')
    expect(summary).toHaveTextContent('条件なし')

    const lastLogRequest = () => new URL(String(fetchMock.mock.calls.filter(([input]) => String(input).startsWith('/api/logs')).at(-1)![0]), 'http://test')
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 51–100 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('offset')).toBe('50')
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
    fireEvent.change(screen.getByLabelText('接続先ID'), { target: { value: 'esxi-1' } })
    fireEvent.change(screen.getByLabelText('ログ種別'), { target: { value: 'hostd' } })
    fireEvent.change(screen.getByLabelText('重大度'), { target: { value: 'error' } })
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(lastLogRequest().searchParams.get('message_contains')).toBe('Storage'))
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(lastLogRequest().searchParams.get('source_id')).toBe('esxi-1')
    expect(lastLogRequest().searchParams.get('log_kind')).toBe('hostd')
    expect(lastLogRequest().searchParams.get('severity')).toBe('error')
    fireEvent.click(summary)
    expect(details).not.toHaveAttribute('open')
    expect(summary).toHaveTextContent('接続先ID「esxi-1」 · 種別「hostd」 · 重大度「error」 · 本文「Storage」')

    await waitFor(() => expect(screen.getByRole('button', { name: '次へ' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 51–100 件を表示')).toBeInTheDocument())
    fireEvent.click(summary)
    fireEvent.click(screen.getByRole('button', { name: '過去 24 時間' }))
    await waitFor(() => expect(lastLogRequest().searchParams.has('from')).toBe(true))
    expect(lastLogRequest().searchParams.has('to')).toBe(true)
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(summary).not.toHaveTextContent('開始指定なし')
    fireEvent.change(screen.getByLabelText('開始日'), { target: { value: '2026-01-01' } })
    await waitFor(() => expect(lastLogRequest().searchParams.get('from')).toContain('2026-01-01'))
  })

  it('uses the selected page size for fetching, pagination and the final page', async () => {
    window.history.replaceState(null, '', '#/logs?vcenter_id=vc-1&from=2026-10-02T09%3A55%3A25Z&to=2026-10-02T10%3A05%3A25Z')
    let total = 101
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
      return response({ items: [row], total })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    const lastLogRequest = () => new URL(String(fetchMock.mock.calls.filter(([input]) => String(input).startsWith('/api/logs')).at(-1)![0]), 'http://test')
    await waitFor(() => expect(screen.getByText('全 101 件中 1–50 件を表示')).toBeInTheDocument())
    expect(screen.getByLabelText('表示件数')).toHaveValue('50')
    expect(lastLogRequest().searchParams.get('limit')).toBe('50')
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 51–100 件を表示')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('表示件数'), { target: { value: '20' } })
    await waitFor(() => expect(screen.getByText('全 101 件中 1–20 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('limit')).toBe('20')
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(lastLogRequest().searchParams.get('vcenter_id')).toBe('vc-1')
    expect(lastLogRequest().searchParams.get('from')).toBe('2026-10-02T09:55:25Z')
    expect(lastLogRequest().searchParams.get('to')).toBe('2026-10-02T10:05:25Z')
    expect(screen.getByRole('button', { name: '前へ' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 21–40 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('offset')).toBe('20')

    total = 15
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 15 件中 1–15 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(screen.getByRole('button', { name: '次へ' })).toBeDisabled()

    total = 101
    fireEvent.change(screen.getByLabelText('表示件数'), { target: { value: '100' } })
    await waitFor(() => expect(screen.getByText('全 101 件中 1–100 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('limit')).toBe('100')
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 101–101 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('offset')).toBe('100')
    expect(screen.getByRole('button', { name: '次へ' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '前へ' }))
    await waitFor(() => expect(screen.getByText('全 101 件中 1–100 件を表示')).toBeInTheDocument())
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')

    fireEvent.change(screen.getByLabelText('表示件数'), { target: { value: '200' } })
    await waitFor(() => expect(lastLogRequest().searchParams.get('limit')).toBe('200'))
    await waitFor(() => expect(screen.getByText('全 101 件中 1–101 件を表示')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '次へ' })).toBeDisabled()
  })

})
