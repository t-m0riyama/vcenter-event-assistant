import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TimeZoneProvider, TimeZoneSelect } from '../../datetime/TimeZoneProvider'
import { onUnauthorized, SESSION_EXPIRED_MESSAGE, setExpectedPrincipal } from '../../api'
import { LogsPanel } from './LogsPanel'
import { downloadLogCsv } from './logExport'

/** 上のページ切り替え。下にも同じボタンと件数があるので、上に絞って探す。 */
const pager = () => within(screen.getByRole('navigation', { name: 'ページ切り替え（上）' }))

vi.mock('./logExport', async (importOriginal) => ({
  ...await importOriginal<typeof import('./logExport')>(), downloadLogCsv: vi.fn(),
}))

const row = {
  id: 1, vcenter_id: 'vc-1', source_id: 'esxi-1', host: 'esxi.local', log_kind: 'vmkernel',
  file_generation: 'gen-1', byte_offset: 12, occurred_at: null,
  collected_at: '2026-10-02T10:00:00Z', effective_at: '2026-10-02T10:00:00Z', severity: 'error', message: 'Storage error\n stack trace',
}
const response = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200 }))
let authResponse: () => Promise<Response> = () =>
  Promise.resolve(new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-alice:s1' } }))
const linkedUrl = '#/logs?vcenter_id=vc-1&from=2026-10-02T09%3A55%3A25Z&to=2026-10-02T10%3A05%3A25Z'

function mockFetch(logPage: (params: URLSearchParams) => Promise<Response>) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
    if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
    if (url.includes('/api/auth/me')) return authResponse()
    return logPage(new URL(url, 'http://test').searchParams)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  setExpectedPrincipal(null)
  authResponse = () =>
    Promise.resolve(new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-alice:s1' } }))
  localStorage.removeItem('vea.displayTimeZone')
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('LogsPanel CSV', () => {
  it('starts a native download with captured filters and zone, without JSON export requests', async () => {
    setExpectedPrincipal('id-alice:s1')
    localStorage.setItem('vea.displayTimeZone', 'Asia/Tokyo')
    window.history.replaceState(null, '', linkedUrl)
    const fetchMock = mockFetch(() => response({ items: [row], total: 201 }))
    render(<TimeZoneProvider><TimeZoneSelect /><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('接続先ID'), { target: { value: 'esxi-1' } })
    fireEvent.change(screen.getByLabelText('ログ種別'), { target: { value: 'vmkernel' } })
    fireEvent.change(screen.getByLabelText('重大度'), { target: { value: 'error' } })
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(pager().getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(pager().getByText('全 201 件中 51–100 件を表示')).toBeInTheDocument())
    const requests = fetchMock.mock.calls.length
    fireEvent.click(button)
    await waitFor(() => expect(downloadLogCsv).toHaveBeenCalledTimes(1))
    // ダウンロード前のセッション確認（/api/auth/me）だけで、JSON のエクスポート要求はしない
    expect(fetchMock.mock.calls.slice(requests).map(([u]) => String(u))).toEqual(['/api/auth/me'])
    const url = new URL(vi.mocked(downloadLogCsv).mock.calls[0][0], 'http://test')
    expect(url.pathname).toBe('/api/logs/export.csv')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      time_zone: 'Asia/Tokyo', vcenter_id: 'vc-1', source_id: 'esxi-1', log_kind: 'vmkernel',
      severity: 'error', message_contains: 'Storage', from: '2026-10-02T09:55:25Z', to: '2026-10-02T10:05:25Z',
      vea_expected_principal: 'id-alice:s1',
    })
    expect(screen.getByText(/ダウンロードを開始しました/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('表示タイムゾーン'), { target: { value: 'UTC' } })
    expect(url.searchParams.get('time_zone')).toBe('Asia/Tokyo')
  })

  it('reports a failure to start a download and permits retry', async () => {
    const onError = vi.fn()
    mockFetch(() => response({ items: [row], total: 1 }))
    vi.mocked(downloadLogCsv).mockImplementationOnce(() => { throw new Error('download blocked') })
    render(<TimeZoneProvider><LogsPanel onError={onError} /></TimeZoneProvider>)
    const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(onError).toHaveBeenCalledWith('download blocked'))
    expect(screen.queryByText(/ダウンロードを開始しました/)).not.toBeInTheDocument()
    fireEvent.click(button)
    expect(await screen.findByText(/ダウンロードを開始しました/)).toBeInTheDocument()
  })

  it('does not start a download once the session has expired', async () => {
    const onError = vi.fn()
    authResponse = () => Promise.resolve(new Response('{"detail":"x"}', { status: 401 }))
    const unauthorized = vi.fn()
    const off = onUnauthorized(unauthorized)
    try {
      mockFetch(() => response({ items: [row], total: 1 }))
      render(<TimeZoneProvider><LogsPanel onError={onError} /></TimeZoneProvider>)
      const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
      await waitFor(() => expect(button).toBeEnabled())
      fireEvent.click(button)
      await waitFor(() => expect(onError).toHaveBeenCalledWith(SESSION_EXPIRED_MESSAGE))
      expect(unauthorized).toHaveBeenCalled()
      expect(downloadLogCsv).not.toHaveBeenCalled()
    } finally {
      off()
    }
  })

  it('disables export during loading, for empty results and for an invalid range', async () => {
    let finish!: (response: Response) => void
    let total = 0
    let pending = true
    mockFetch(() => pending ? new Promise<Response>((resolve) => { finish = resolve }) : response({ items: [row], total }))
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
    expect(button).toBeDisabled()
    pending = false
    await act(async () => { finish(await response({ items: [], total: 0 })) })
    expect(button).toBeDisabled()
    total = 1
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.change(screen.getByLabelText('終了日'), { target: { value: '2026-01-01' } })
    fireEvent.change(screen.getByLabelText('開始日'), { target: { value: '2026-01-02' } })
    expect(button).toBeDisabled()
    fireEvent.click(button)
    expect(downloadLogCsv).not.toHaveBeenCalled()
  })
})
