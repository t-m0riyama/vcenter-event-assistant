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
