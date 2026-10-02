import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TimeZoneProvider, TimeZoneSelect } from '../../datetime/TimeZoneProvider'
import { LogsPanel } from './LogsPanel'
import { downloadLogListCsv, logRowsToCsv } from './logExport'

vi.mock('./logExport', async (importOriginal) => ({
  ...await importOriginal<typeof import('./logExport')>(), downloadLogListCsv: vi.fn(),
}))

const row = {
  id: 1, vcenter_id: 'vc-1', source_id: 'esxi-1', host: 'esxi.local', log_kind: 'vmkernel',
  file_generation: 'gen-1', byte_offset: 12, occurred_at: null,
  collected_at: '2026-10-02T10:00:00Z', effective_at: '2026-10-02T10:00:00Z', severity: 'error', message: 'Storage error\n stack trace',
}
const response = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { status: 200 }))
const linkedUrl = '#/logs?vcenter_id=vc-1&from=2026-10-02T09%3A55%3A25Z&to=2026-10-02T10%3A05%3A25Z'

function mockFetch(logPage: (params: URLSearchParams) => Promise<Response>) {
  const mock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
    if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
    return logPage(new URL(url, 'http://test').searchParams)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

afterEach(() => {
  localStorage.removeItem('vea.displayTimeZone')
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('LogsPanel CSV', () => {
  it('exports all filtered pages from offset zero and freezes conditions and time zone', async () => {
    localStorage.setItem('vea.displayTimeZone', 'Asia/Tokyo')
    window.history.replaceState(null, '', linkedUrl)
    let finishFirst!: (response: Response) => void
    const firstPage = new Promise<Response>((resolve) => { finishFirst = resolve })
    const exportQueries: URLSearchParams[] = []
    const firstRows = Array.from({ length: 200 }, (_, i) => ({ ...row, id: 201 - i }))
    mockFetch((params) => {
      if (params.get('limit') !== '200') return response({ items: [row], total: 201 })
      exportQueries.push(params)
      return params.get('offset') === '0' ? firstPage : response({ items: [row], total: 201 })
    })
    render(<TimeZoneProvider><TimeZoneSelect /><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
    await waitFor(() => expect(button).toBeEnabled())
    expect(button.previousElementSibling).toHaveClass('toolbar__meta')
    expect(button).toHaveClass('btn', 'btn--gray')
    const toolbar = button.closest('.toolbar')!
    expect([...toolbar.children].indexOf(button)).toBeLessThan([...toolbar.children].indexOf(toolbar.querySelector('details')!))
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('接続先ID'), { target: { value: 'esxi-1' } })
    fireEvent.change(screen.getByLabelText('ログ種別'), { target: { value: 'vmkernel' } })
    fireEvent.change(screen.getByLabelText('重大度'), { target: { value: 'error' } })
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'Storage' } })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(screen.getByText('全 201 件中 51–100 件を表示')).toBeInTheDocument())
    fireEvent.click(button)
    expect(screen.getByRole('button', { name: '出力中…' })).toBeDisabled()
    fireEvent.click(button)
    expect(exportQueries).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'changed' } })
    fireEvent.change(screen.getByLabelText('表示タイムゾーン'), { target: { value: 'UTC' } })
    await act(async () => { finishFirst(await response({ items: firstRows, total: 201 })) })
    await waitFor(() => expect(downloadLogListCsv).toHaveBeenCalledTimes(1))
    expect(exportQueries.map((q) => Object.fromEntries(q))).toEqual([0, 200].map((offset) => ({
      limit: '200', offset: String(offset), vcenter_id: 'vc-1', source_id: 'esxi-1', log_kind: 'vmkernel',
      severity: 'error', message_contains: 'Storage', from: '2026-10-02T09:55:25Z', to: '2026-10-02T10:05:25Z',
    })))
    expect(downloadLogListCsv).toHaveBeenCalledWith(
      logRowsToCsv([...firstRows, row], new Map([['vc-1', 'Lab']]), 'Asia/Tokyo'),
      expect.stringMatching(/^logs-\d{8}-\d{6}\.csv$/),
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeEnabled())
  })

  it('reports a later-page failure without downloading partial CSV and allows retry', async () => {
    const onError = vi.fn()
    let fail = true
    mockFetch((params) => {
      if (params.get('limit') !== '200') return response({ items: [row], total: 2 })
      if (params.get('offset') === '0') return response({ items: [row], total: fail ? 2 : 1 })
      return Promise.reject(new Error('offline'))
    })
    render(<TimeZoneProvider><LogsPanel onError={onError} /></TimeZoneProvider>)
    const button = screen.getByRole('button', { name: 'CSVをダウンロード' })
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    await waitFor(() => expect(onError).toHaveBeenCalledWith('offline'))
    expect(downloadLogListCsv).not.toHaveBeenCalled()
    expect(button).toBeEnabled()
    fail = false
    fireEvent.click(button)
    await waitFor(() => expect(downloadLogListCsv).toHaveBeenCalledTimes(1))
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
    expect(downloadLogListCsv).not.toHaveBeenCalled()
  })
})
