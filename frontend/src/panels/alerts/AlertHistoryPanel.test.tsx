import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AlertHistoryPanel } from './AlertHistoryPanel'
import { TimeZoneContext } from '../../datetime/timeZoneContext'
import { apiDelete, apiGet } from '../../api'

vi.mock('../../api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() }))

const base = {
  rule_id: 1, rule_name: 'CPU', rule_type: 'metric_threshold', alert_level: 'warning',
  state: 'firing', context_key: 'host-1', notified_at: '2026-10-03T00:00:00Z',
  channel: 'email', success: null, error_message: null, can_resolve: false,
  last_attempt_at: null, next_attempt_at: null,
}

function show() {
  return render(
    <TimeZoneContext.Provider value={{ timeZone: 'UTC', setTimeZone: vi.fn() }}>
      <AlertHistoryPanel onError={vi.fn()} />
    </TimeZoneContext.Provider>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('delivery history', () => {
  it('distinguishes waiting, retrying, successful, exhausted and skipped notifications', async () => {
    vi.mocked(apiGet).mockResolvedValue({ total: 5, items: [
      { ...base, id: 1, delivery_status: 'pending', attempt_count: 0 },
      { ...base, id: 2, delivery_status: 'retrying', success: false, attempt_count: 2,
        error_message: 'timeout', next_attempt_at: '2026-10-03T00:02:00Z' },
      { ...base, id: 3, delivery_status: 'succeeded', success: true, attempt_count: 3 },
      { ...base, id: 4, delivery_status: 'failed', success: false, attempt_count: 10 },
      { ...base, id: 5, delivery_status: 'skipped', channel: 'none', attempt_count: null },
    ] })
    show()
    expect(await screen.findByText('配送待ち')).toBeInTheDocument()
    expect(screen.getByText('再送待ち')).toHaveAttribute('title', 'timeout')
    expect(screen.getByText('成功')).toBeInTheDocument()
    expect(screen.getByText('打ち切り')).toBeInTheDocument()
    expect(screen.getByText('未送信')).toBeInTheDocument()
    expect(screen.getByText('試行: 2回')).toBeInTheDocument()
    expect(screen.getByText('試行: 不明回')).toBeInTheDocument()
    expect(screen.getByText(/次回:/)).toBeInTheDocument()
  })

  it('explains cancellation when deleting a queued notification', async () => {
    vi.mocked(apiGet).mockResolvedValue({ total: 1, items: [
      { ...base, id: 42, delivery_status: 'retrying', attempt_count: 1 },
    ] })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    show()
    const row = (await screen.findByText('再送待ち')).closest('tr')!
    fireEvent.click(within(row).getByRole('button', { name: '削除' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('待機中の通知も取り消します'))
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/api/alerts/history/42'))
    confirm.mockRestore()
  })
})

describe('pagination', () => {
  it('requests one page at a time and moves with the bottom controls too', async () => {
    vi.mocked(apiGet).mockResolvedValue({ total: 120, items: [
      { ...base, id: 1, delivery_status: 'succeeded', success: true, attempt_count: 1 },
    ] })
    show()
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/alerts/history?limit=50&offset=0'))
    const top = await screen.findByRole('navigation', { name: 'ページ切り替え（上）' })
    expect(within(top).getByText('全 120 件中 1–50 件を表示')).toBeInTheDocument()
    const bottom = screen.getByRole('navigation', { name: 'ページ切り替え（下）' })
    fireEvent.click(within(bottom).getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/alerts/history?limit=50&offset=50'))
    expect(within(top).getByText('全 120 件中 51–100 件を表示')).toBeInTheDocument()
  })

  it('goes back to the last page when the current page becomes empty', async () => {
    vi.mocked(apiGet).mockResolvedValue({ total: 60, items: [
      { ...base, id: 1, delivery_status: 'succeeded', success: true, attempt_count: 1 },
    ] })
    show()
    const top = await screen.findByRole('navigation', { name: 'ページ切り替え（上）' })
    fireEvent.click(within(top).getByRole('button', { name: '次へ' }))
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/alerts/history?limit=50&offset=50'))
    vi.mocked(apiGet).mockResolvedValue({ total: 50, items: [] })
    fireEvent.click(screen.getByRole('button', { name: '一覧を更新' }))
    await waitFor(() => expect(within(top).getByText('全 50 件中 1–50 件を表示')).toBeInTheDocument())
  })

  it('ignores a response for a page the user has already left', async () => {
    let resolveFirstPage: (value: unknown) => void = () => {}
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path.endsWith('offset=0')) {
        return new Promise((resolve) => {
          resolveFirstPage = resolve
        })
      }
      return Promise.resolve({ total: 120, items: [
        { ...base, id: 2, context_key: 'page-2', delivery_status: 'succeeded', success: true, attempt_count: 1 },
      ] })
    })
    show()
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/alerts/history?limit=50&offset=0'))
    // 最初の応答を待たずに次のページへ進むため、件数が分かっている状態を作る。
    resolveFirstPage({ total: 120, items: [
      { ...base, id: 1, context_key: 'page-1', delivery_status: 'succeeded', success: true, attempt_count: 1 },
    ] })
    expect(await screen.findByText('page-1')).toBeInTheDocument()
    vi.mocked(apiGet).mockImplementation((path: string) => {
      if (path.endsWith('offset=0')) {
        return new Promise((resolve) => {
          resolveFirstPage = resolve
        })
      }
      return Promise.resolve({ total: 120, items: [
        { ...base, id: 2, context_key: 'page-2', delivery_status: 'succeeded', success: true, attempt_count: 1 },
      ] })
    })
    // 1 ページ目の再取得（応答待ち）の間に 2 ページ目へ進む。
    fireEvent.click(screen.getByRole('button', { name: '一覧を更新' }))
    const top = screen.getByRole('navigation', { name: 'ページ切り替え（上）' })
    fireEvent.click(within(top).getByRole('button', { name: '次へ' }))
    expect(await screen.findByText('page-2')).toBeInTheDocument()
    // 古い 1 ページ目の応答が後から届いても、2 ページ目の表示は変わらない。
    resolveFirstPage({ total: 120, items: [
      { ...base, id: 3, context_key: 'stale-page-1', delivery_status: 'succeeded', success: true, attempt_count: 1 },
    ] })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByText('stale-page-1')).not.toBeInTheDocument()
    expect(screen.getByText('page-2')).toBeInTheDocument()
    expect(within(top).getByText('全 120 件中 51–100 件を表示')).toBeInTheDocument()
  })
})
