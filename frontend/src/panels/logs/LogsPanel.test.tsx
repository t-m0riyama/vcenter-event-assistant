/** @vitest-environment happy-dom */
import { Profiler } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GENERIC_API_ERROR } from '../../api'
import { LogsPanel } from './LogsPanel'
import { NEW_LOG_PATTERN_EXAMPLE } from '../../test/timelineViewFixtures'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'

/** 上のページ切り替え。下にも同じボタンと件数があるので、上に絞って探す。 */
const pager = () => within(screen.getByRole('navigation', { name: 'ページ切り替え（上）' }))

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
  describe('型ごとの集計', () => {
    const pattern = {
      ...NEW_LOG_PATTERN_EXAMPLE,
      last_utc: '2026-03-22T00:15:00Z',
    }

    const patternPage = (items = [pattern]) => response({ items, total: items.length, truncated: false, pending_count: 0 })
    const busy = () => Promise.resolve(new Response('{}', { status: 503, headers: { 'Retry-After': '1' } }))
    const linkedHash = '#/logs?vcenter_id=vc-1&from=2026-03-22T00:00:00Z&to=2026-03-22T01:00:00Z'

    function renderPatterns({
      linked = true,
      patternKey,
      timeZone = 'UTC',
      patterns = () => response({ items: [pattern], total: 201, truncated: true, pending_count: 4 }),
    }: { linked?: boolean; patternKey?: string; timeZone?: string; patterns?: (params: URLSearchParams) => Promise<Response> } = {}) {
      localStorage.setItem('vea.displayTimeZone', timeZone)
      if (linked) {
        window.history.replaceState(null, '', linkedHash + (patternKey ? `&pattern_key=${encodeURIComponent(patternKey)}` : ''))
      }
      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const { pathname, searchParams } = new URL(String(input), 'http://test')
        if (pathname === '/api/vcenters') return response([{ id: 'vc-1', name: 'Lab' }, { id: pattern.vcenter_id, name: pattern.vcenter_name }])
        if (pathname === '/api/plugins/collectors') return collectorResponse('ok')
        if (pathname === '/api/logs/patterns') return patterns(searchParams)
        return response({ items: [row], total: 1 })
      })
      vi.stubGlobal('fetch', fetchMock)
      const onError = vi.fn()
      render(<TimeZoneProvider><LogsPanel onError={onError} /></TimeZoneProvider>)
      const requests = (path: string) => fetchMock.mock.calls
        .map(([input]) => new URL(String(input), 'http://test'))
        .filter(({ pathname }) => pathname === path)
      return { requests, patternRequests: () => requests('/api/logs/patterns'), onError }
    }

    const openPatterns = () => fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
    const advance = async (ms: number) => {
      await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
    }

    it('一覧から集計に切り替え、型の行を押すと vCenter と型で絞った一覧を開く', async () => {
      const { requests } = renderPatterns()
      await screen.findByText('Storage error')
      expect(screen.getByRole('button', { name: '一覧' })).toHaveAttribute('aria-pressed', 'true')
      fireEvent.change(screen.getByLabelText('vCenter'), { target: { value: '' } })
      fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
      const template = await screen.findByRole('button', { name: pattern.template })
      const tr = template.closest('tr')
      const utcFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'medium', timeZone: 'UTC' })
      const timestamps = ['2026-03-22T00:10:00Z', '2026-03-22T00:15:00Z', '2026-03-21T00:00:00Z']
      for (const value of ['vmkernel', 'vc-pattern', '3', 'warning', ...timestamps.map((at) => utcFormat.format(new Date(at)))]) {
        expect(tr).toHaveTextContent(value)
      }
      expect(screen.getByText(/全 201 個の型のうち.*1 個/)).toBeInTheDocument()
      expect(screen.getByText(/型の計算待ち.*4 件/)).toBeInTheDocument()
      expect(screen.queryByText('Storage error')).not.toBeInTheDocument()
      expect(Object.fromEntries(requests('/api/logs/patterns')[0].searchParams)).toEqual({
        from: '2026-03-22T00:00:00Z', to: '2026-03-22T01:00:00Z',
      })
      fireEvent.click(tr!)
      await screen.findByText('Storage error')
      expect(screen.getByRole('button', { name: '一覧' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByText(/型で絞り込み中/)).toHaveTextContent(pattern.template)
      // 型ごとの表は型で絞らないので、型ごとに戻ったら絞り込み中の表示を出さない
      fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
      expect(screen.queryByText(/型で絞り込み中/)).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '一覧' }))
      expect(screen.getByText(/型で絞り込み中/)).toHaveTextContent(pattern.template)
      expect(Object.fromEntries(requests('/api/logs').at(-1)!.searchParams)).toMatchObject({
        vcenter_id: pattern.vcenter_id, pattern_key: pattern.pattern_key, offset: '0',
      })
      expect(screen.getByText('絞り込み条件').closest('summary')).toHaveTextContent('型「Storage retry')
      openPatterns()
      await screen.findByRole('table', { name: 'ログの型ごとの集計' })
      expect(requests('/api/logs/patterns').at(-1)!.searchParams.has('pattern_key')).toBe(false)

      fireEvent.click(screen.getByRole('button', { name: '一覧' }))
      fireEvent.click(screen.getByRole('button', { name: '型の絞り込みを解除' }))
      await waitFor(() => {
        const params = requests('/api/logs').at(-1)!.searchParams
        expect(params.has('pattern_key')).toBe(false)
        expect(params.has('vcenter_id')).toBe(false)
      })
      expect(screen.getByLabelText('vCenter')).toHaveValue('')
    })

    it('ログタブが開いた後に受け取った型のリンクを、夏時間の切り替えをまたいでも適用する', async () => {
      const { requests } = renderPatterns({ linked: false, timeZone: 'America/New_York' })
      await screen.findByText('Storage error')
      fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
      const params = new URLSearchParams({
        vcenter_id: pattern.vcenter_id,
        pattern_key: pattern.pattern_key,
        from: '2026-11-01T05:50:00Z',
        to: '2026-11-01T06:10:00Z',
      })
      window.location.hash = `#/logs?${params}`
      await waitFor(() => expect(Object.fromEntries(requests('/api/logs').at(-1)!.searchParams)).toMatchObject(
        Object.fromEntries(params),
      ))
      expect(screen.getByRole('button', { name: '一覧' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByText(/型で絞り込み中/)).toBeInTheDocument()
      await waitFor(() => expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeEnabled())
    })

    it('期間を指定していないときは集計を要求しない', async () => {
      const { requests } = renderPatterns({ linked: false })
      await screen.findByText('Storage error')
      fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
      expect(screen.getByText(/開始と終了を指定/)).toBeInTheDocument()
      expect(requests('/api/logs/patterns')).toHaveLength(0)
    })

    it.each([
      { detail: { code: 'log_pattern_scan_limit' }, limit: true },
      { detail: [{ loc: ['query', 'from'], msg: 'Invalid datetime' }], limit: false },
    ])('422 の理由に合った案内を出す（上限超過 $limit）', async ({ detail, limit }) => {
      const { onError } = renderPatterns({
        patterns: () => Promise.resolve(new Response(JSON.stringify({ detail }), { status: 422 })),
      })
      await screen.findByText('Storage error')
      fireEvent.click(screen.getByRole('button', { name: '型ごと' }))
      if (limit) {
        expect(await screen.findByText(/期間を短くするか、条件を追加して絞り込んでください/)).toBeInTheDocument()
      } else {
        await waitFor(() => expect(onError).toHaveBeenCalledWith('query.from: Invalid datetime'))
        expect(screen.queryByText(/期間を短くするか、条件を追加して絞り込んでください/)).not.toBeInTheDocument()
      }
    })
    it.each([true, false])('503 の Retry-After を待って 1 回だけ再試行する（回復 %s）', async (recovers) => {
      const fetchPatterns = vi.fn()
        .mockImplementationOnce(busy)
        .mockImplementationOnce(recovers ? () => patternPage() : busy)
      const { patternRequests } = renderPatterns({ patterns: fetchPatterns })
      await screen.findByText('Storage error')
      vi.useFakeTimers()
      openPatterns()
      await advance(400)
      expect(patternRequests()).toHaveLength(1)
      expect(screen.getByRole('status')).toHaveTextContent('読み込み中')
      await advance(999)
      expect(patternRequests()).toHaveLength(1)
      await advance(1)
      expect(patternRequests()).toHaveLength(2)
      if (recovers) expect(screen.getByRole('button', { name: pattern.template })).toBeInTheDocument()
      else expect(screen.getByText('集計が混み合っています。しばらくしてから再度お試しください。')).toBeInTheDocument()
      await advance(2_000)
      expect(patternRequests()).toHaveLength(2)
    })

    it('本文と接続先IDを続けて入力しても最後の条件だけで集計する', async () => {
      const { patternRequests } = renderPatterns()
      await screen.findByText('Storage error')
      openPatterns()
      await screen.findByRole('button', { name: pattern.template })
      fireEvent.click(screen.getByText('絞り込み条件'))
      const field = screen.getByLabelText('本文（含む）')
      const source = screen.getByLabelText('接続先ID')
      vi.useFakeTimers()
      fireEvent.change(field, { target: { value: 'st' } })
      await advance(100)
      fireEvent.change(field, { target: { value: 'storage' } })
      await advance(100)
      fireEvent.change(source, { target: { value: 'esxi-1' } })
      await advance(399)
      expect(patternRequests()).toHaveLength(1)
      await advance(1)
      expect(patternRequests()).toHaveLength(2)
      expect(Object.fromEntries(patternRequests()[1].searchParams)).toMatchObject({
        source_id: 'esxi-1', message_contains: 'storage',
      })
    })

    it('読み込み中と空の結果を表示し、条件変更後に到着した結果を表示しない', async () => {
      const pending: Array<(result: Response) => void> = []
      const { patternRequests } = renderPatterns({
        patterns: () => new Promise((resolve) => { pending.push(resolve) }),
      })
      await screen.findByText('Storage error')
      openPatterns()
      expect(screen.getByRole('status')).toHaveTextContent('読み込み中')
      await waitFor(() => expect(patternRequests()).toHaveLength(1))
      await act(async () => { pending[0](await patternPage()) })
      expect(screen.getByRole('button', { name: pattern.template })).toBeInTheDocument()

      const field = screen.getByLabelText('本文（含む）')
      fireEvent.change(field, { target: { value: 'older' } })
      expect(screen.queryByRole('button', { name: pattern.template })).not.toBeInTheDocument()
      await waitFor(() => expect(patternRequests()).toHaveLength(2))
      fireEvent.change(field, { target: { value: 'newer' } })
      await act(async () => { pending[1](await patternPage()) })
      expect(screen.queryByRole('button', { name: pattern.template })).not.toBeInTheDocument()
      await waitFor(() => expect(patternRequests()).toHaveLength(3))
      await act(async () => { pending[2](await patternPage([])) })
      expect(screen.getByText('条件に一致する集計済みの型はありません')).toBeInTheDocument()
    })

    it('集計の一般エラーを表示する', async () => {
      const { onError, patternRequests } = renderPatterns({
        patterns: () => Promise.resolve(new Response('{}', { status: 500 })),
      })
      await screen.findByText('Storage error')
      openPatterns()
      await waitFor(() => expect(onError).toHaveBeenCalledWith(GENERIC_API_ERROR))
      expect(patternRequests()).toHaveLength(1)
      expect(screen.queryByText('読み込み中…')).not.toBeInTheDocument()
    })

    it('リンク先の型名の取得を 503 後に再試行し、通常の集計から型キーを外す', async () => {
      const lookup = vi.fn().mockImplementationOnce(busy).mockImplementationOnce(() => patternPage())
      const { patternRequests } = renderPatterns({
        patternKey: pattern.pattern_key,
        patterns: (params) => params.has('pattern_key') ? lookup() : patternPage([]),
      })
      expect(await screen.findByText(pattern.template, { selector: 'code' }, { timeout: 2_500 })).toBeInTheDocument()
      expect(lookup).toHaveBeenCalledTimes(2)
      expect(Object.fromEntries(patternRequests()[0].searchParams)).toEqual({
        vcenter_id: 'vc-1', pattern_key: pattern.pattern_key, from: '2026-03-22T00:00:00Z', to: '2026-03-22T01:00:00Z',
      })
      openPatterns()
      await screen.findByText('条件に一致する集計済みの型はありません')
      expect(patternRequests()).toHaveLength(3)
      expect(patternRequests().at(-1)!.searchParams.has('pattern_key')).toBe(false)
    })

    it.each(['解除', 'vCenter を変更'])('型名を取得できないリンクでキーを表示し、型の指定を外す（%s）', async (action) => {
      const { requests, patternRequests, onError } = renderPatterns({
        patternKey: '0123456789abcdef',
        patterns: () => patternPage([]),
      })
      await screen.findByText('Storage error')
      expect(screen.getByText('型で絞り込み中（キー 01234567…）')).toBeInTheDocument()
      await waitFor(() => expect(patternRequests()).toHaveLength(1))
      if (action === '解除') fireEvent.click(screen.getByRole('button', { name: '型の絞り込みを解除' }))
      else fireEvent.change(screen.getByLabelText('vCenter'), { target: { value: pattern.vcenter_id } })
      const expectedVCenter = action === '解除' ? 'vc-1' : pattern.vcenter_id
      await waitFor(() => {
        const params = requests('/api/logs').at(-1)!.searchParams
        expect(params.has('pattern_key')).toBe(false)
        expect(params.get('vcenter_id')).toBe(expectedVCenter)
      })
      expect(screen.queryByText(/型で絞り込み中/)).not.toBeInTheDocument()
      expect(window.location.hash).not.toContain('pattern_key=')
      expect(window.location.hash).toContain('from=')
      expect(onError).not.toHaveBeenCalledWith(expect.any(String))
    })

  })

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
    await waitFor(() => expect(pager().getByText('全 101 件中 1–50 件を表示')).toBeInTheDocument())
    const summary = screen.getByText('絞り込み条件').closest('summary')!
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(summary).toHaveTextContent('開始指定なし ～ 終了指定なし')
    expect(summary).toHaveTextContent('条件なし')

    const lastLogRequest = () => new URL(String(fetchMock.mock.calls.filter(([input]) => String(input).startsWith('/api/logs')).at(-1)![0]), 'http://test')
    fireEvent.click(pager().getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(pager().getByText('全 101 件中 51–100 件を表示')).toBeInTheDocument())
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

    await waitFor(() => expect(pager().getByRole('button', { name: '次へ' })).toBeEnabled())
    fireEvent.click(pager().getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(pager().getByText('全 101 件中 51–100 件を表示')).toBeInTheDocument())
    fireEvent.click(summary)
    fireEvent.click(screen.getByRole('button', { name: '過去 24 時間' }))
    await waitFor(() => expect(lastLogRequest().searchParams.has('from')).toBe(true))
    expect(lastLogRequest().searchParams.has('to')).toBe(true)
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(summary).not.toHaveTextContent('開始指定なし')
    fireEvent.change(screen.getByLabelText('開始日'), { target: { value: '2026-01-01' } })
    await waitFor(() => expect(lastLogRequest().searchParams.get('from')).toContain('2026-01-01'))
  })

  async function renderPagination() {
    window.history.replaceState(null, '', '#/logs?vcenter_id=vc-1&from=2026-10-02T09%3A55%3A25Z&to=2026-10-02T10%3A05%3A25Z')
    const data = { total: 101 }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([{ id: 'vc-1', name: 'Lab' }])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
      return response({ items: [row], total: data.total })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><LogsPanel onError={vi.fn()} /></TimeZoneProvider>)
    await pager().findByText('全 101 件中 1–50 件を表示')
    // These controls keep their identity across page updates. Query each only once.
    const pageSize = screen.getByLabelText('表示件数')
    const next = pager().getByRole('button', { name: '次へ' })
    const previous = pager().getByRole('button', { name: '前へ' })
    const status = screen.getByRole('status')
    const lastLogRequest = () => new URL(String(fetchMock.mock.calls.filter(([input]) => String(input).startsWith('/api/logs')).at(-1)![0]), 'http://test')
    const expectPage = async (text: string) => {
      await waitFor(() => expect(status).toHaveTextContent(text))
    }
    return { data, pageSize, next, previous, lastLogRequest, expectPage }
  }

  it('resets pagination and preserves linked filters when selecting a smaller page size', async () => {
    const { pageSize, next, previous, lastLogRequest, expectPage } = await renderPagination()
    expect(pageSize).toHaveValue('50')
    expect(lastLogRequest().searchParams.get('limit')).toBe('50')
    fireEvent.click(next)
    await expectPage('全 101 件中 51–100 件を表示')

    fireEvent.change(pageSize, { target: { value: '20' } })
    await expectPage('全 101 件中 1–20 件を表示')
    expect(lastLogRequest().searchParams.get('limit')).toBe('20')
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(lastLogRequest().searchParams.get('vcenter_id')).toBe('vc-1')
    expect(lastLogRequest().searchParams.get('from')).toBe('2026-10-02T09:55:25Z')
    expect(lastLogRequest().searchParams.get('to')).toBe('2026-10-02T10:05:25Z')
    expect(previous).toBeDisabled()
    fireEvent.click(next)
    await expectPage('全 101 件中 21–40 件を表示')
    expect(lastLogRequest().searchParams.get('offset')).toBe('20')
  })

  it('corrects the requested offset when the total shrinks below the selected page size', async () => {
    const { data, pageSize, next, previous, lastLogRequest, expectPage } = await renderPagination()
    fireEvent.change(pageSize, { target: { value: '20' } })
    await expectPage('全 101 件中 1–20 件を表示')
    fireEvent.click(next)
    await expectPage('全 101 件中 21–40 件を表示')

    data.total = 15
    fireEvent.click(next)
    await expectPage('全 15 件中 1–15 件を表示')
    expect(lastLogRequest().searchParams.get('limit')).toBe('20')
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')
    expect(previous).toBeDisabled()
    expect(next).toBeDisabled()
  })

  it('navigates the final page and disables next when a larger page size covers all results', async () => {
    const { pageSize, next, previous, lastLogRequest, expectPage } = await renderPagination()
    fireEvent.change(pageSize, { target: { value: '100' } })
    await expectPage('全 101 件中 1–100 件を表示')
    expect(lastLogRequest().searchParams.get('limit')).toBe('100')
    fireEvent.click(next)
    await expectPage('全 101 件中 101–101 件を表示')
    expect(lastLogRequest().searchParams.get('offset')).toBe('100')
    expect(next).toBeDisabled()
    fireEvent.click(previous)
    await expectPage('全 101 件中 1–100 件を表示')
    expect(lastLogRequest().searchParams.get('offset')).toBe('0')

    fireEvent.change(pageSize, { target: { value: '200' } })
    await expectPage('全 101 件中 1–101 件を表示')
    expect(lastLogRequest().searchParams.get('limit')).toBe('200')
    expect(next).toBeDisabled()
  })

  async function startPageCorrection(total: number) {
    const pending: { params: URLSearchParams; resolve: (value: Response) => void; reject: (reason: Error) => void }[] = []
    const statuses: (string | null)[] = []
    const onError = vi.fn()
    let deferLogs = false
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/vcenters')) return response([])
      if (url.includes('/api/plugins')) return response({ generation: 1, collectors: [] })
      if (!deferLogs) return response({ items: [row], total: 101 })
      return new Promise<Response>((resolve, reject) => {
        pending.push({ params: new URL(url, 'http://test').searchParams, resolve, reject })
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<TimeZoneProvider><Profiler id="logs" onRender={() => {
      statuses.push(screen.getByRole('status').textContent)
    }}><LogsPanel onError={onError} /></Profiler></TimeZoneProvider>)
    await pager().findByText('全 101 件中 1–50 件を表示')
    fireEvent.change(screen.getByLabelText('表示件数'), { target: { value: '20' } })
    await pager().findByText('全 101 件中 1–20 件を表示')
    fireEvent.click(pager().getByRole('button', { name: '次へ' }))
    await pager().findByText('全 101 件中 21–40 件を表示')
    deferLogs = true
    fireEvent.click(pager().getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(pending).toHaveLength(1))
    expect(pending[0].params.get('offset')).toBe('40')
    statuses.length = 0
    await act(async () => {
      pending[0].resolve(await response({ items: [{ ...row, message: 'Out-of-range response' }], total }))
    })
    await waitFor(() => expect(pending).toHaveLength(2))
    return { pending, statuses, onError }
  }

  it.each([
    { total: 15, offset: '0', text: '全 15 件中 1–15 件を表示' },
    { total: 35, offset: '20', text: '全 35 件中 21–35 件を表示' },
    { total: 0, offset: '0', text: '全 0 件' },
  ])('keeps loading until the corrected page completes when total becomes $total', async ({ total, offset, text }) => {
    const { pending, statuses } = await startPageCorrection(total)
    expect(pending[1].params.get('offset')).toBe(offset)
    expect(pending[1].params.get('limit')).toBe('20')
    // Inspect every committed render, including the handoff between requests.
    expect(statuses.length).toBeGreaterThan(0)
    expect(statuses.every((status) => status === '読み込み中…')).toBe(true)
    expect(screen.queryByText('Out-of-range response', { selector: 'summary' })).not.toBeInTheDocument()
    expect(pager().queryByText(text)).not.toBeInTheDocument()
    for (const name of ['前へ', '次へ', 'CSVをダウンロード']) {
      for (const button of screen.getAllByRole('button', { name })) expect(button).toBeDisabled()
    }
    await act(async () => {
      pending[1].resolve(await response({ items: total ? [{ ...row, message: 'Corrected page' }] : [], total }))
    })
    await pager().findByText(text)
    expect(pager().queryByText('読み込み中…')).not.toBeInTheDocument()
    expect(pager().getByRole('button', { name: '次へ' })).toBeDisabled()
    if (total) {
      expect(screen.getByText('Corrected page', { selector: 'summary' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeEnabled()
    } else {
      expect(screen.getByText('条件に一致するログはありません')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeDisabled()
    }
    const previous = pager().getByRole('button', { name: '前へ' })
    if (offset === '0') expect(previous).toBeDisabled()
    else expect(previous).toBeEnabled()
    expect(pending).toHaveLength(2)
  })

  it('reports a corrected-page failure and leaves loading', async () => {
    const { pending, onError } = await startPageCorrection(15)
    await act(async () => { pending[1].reject(new Error('corrected page offline')) })
    expect(onError).toHaveBeenCalledWith('corrected page offline')
    expect(pager().queryByText('読み込み中…')).not.toBeInTheDocument()
    expect(screen.queryByText('Out-of-range response', { selector: 'summary' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeEnabled()
  })

  it('ignores a stale corrected response without clearing the newer request loading state', async () => {
    const { pending, onError } = await startPageCorrection(15)
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('本文（含む）'), { target: { value: 'new filter' } })
    await waitFor(() => expect(pending).toHaveLength(3))
    expect(pending[2].params.get('message_contains')).toBe('new filter')
    expect(pending[2].params.get('offset')).toBe('0')
    await act(async () => {
      pending[1].resolve(await response({ items: [{ ...row, message: 'Stale corrected page' }], total: 15 }))
    })
    expect(pager().getByText('読み込み中…')).toBeInTheDocument()
    expect(screen.queryByText('Stale corrected page', { selector: 'summary' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeDisabled()
    await act(async () => {
      pending[2].resolve(await response({ items: [{ ...row, message: 'New filtered page' }], total: 1 }))
    })
    expect(screen.getByText('New filtered page', { selector: 'summary' })).toBeInTheDocument()
    expect(pager().getByText('全 1 件中 1–1 件を表示')).toBeInTheDocument()
    expect(onError).not.toHaveBeenCalledWith(expect.any(String))
  })

  it('clears loading for an invalid range and ignores a pending corrected response', async () => {
    const { pending, onError } = await startPageCorrection(15)
    fireEvent.click(screen.getByText('絞り込み条件'))
    fireEvent.change(screen.getByLabelText('開始日'), { target: { value: '2026-01-02' } })
    await waitFor(() => expect(pending).toHaveLength(3))
    fireEvent.change(screen.getByLabelText('終了日'), { target: { value: '2026-01-01' } })
    await waitFor(() => expect(pager().queryByText('読み込み中…')).not.toBeInTheDocument())
    expect(onError).toHaveBeenCalledWith(expect.any(String))
    expect(screen.getByRole('button', { name: 'CSVをダウンロード' })).toBeDisabled()
    await act(async () => {
      for (const request of pending.slice(1)) {
        request.resolve(await response({ items: [{ ...row, message: 'Stale range page' }], total: 15 }))
      }
    })
    expect(screen.queryByText('Stale range page', { selector: 'summary' })).not.toBeInTheDocument()
    expect(pending).toHaveLength(3)
  })

})
