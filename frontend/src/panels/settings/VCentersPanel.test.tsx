/**
 * @vitest-environment happy-dom
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'

import { VCentersPanel } from './VCentersPanel'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('VCentersPanel protocol selector', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  beforeEach(() => {
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  it.each([true, false])('vCenter ごとに収集の履歴と件数を表示する（収集有効: %s）', async (enabled) => {
    const id = '11111111-1111-4111-8111-111111111111'
    const at = '2026-04-24T00:00:00Z'
    const failure = '2026-04-24T00:05:00Z'
    const warning = '2026-04-24T00:10:00Z'
    const zone = 'Asia/Tokyo'
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, zone)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({
          enabled, interval_seconds: 300, timeout_seconds: 60,
          vcenters: [{
            vcenter_id: id, vcenter_name: 'lab', is_enabled: true, first_success_at: at,
            last_started_at: failure, last_success_at: at, last_failure_at: failure,
            last_error: '権限不足', last_warning: '関係の件数が急減', last_warning_at: warning,
            object_count: 0, relation_count: 21,
          }],
        })
      : jsonResponse([{
          id, name: 'lab', host: 'vc.example.local', protocol: 'https', port: 443, username: 'operator',
          is_enabled: true, verify_ssl: true, created_at: at,
        }])))

    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    expect(await screen.findByText('権限不足')).toBeInTheDocument()
    expect(screen.getByText('関係の件数が急減')).toBeInTheDocument()
    for (const time of [at, failure, warning]) {
      expect(screen.getByText(formatIsoInTimeZone(time, zone))).toBeInTheDocument()
    }
    expect(screen.getByText(/管理対象 0 件、関係 21 件/)).toBeInTheDocument()
    expect(Boolean(screen.queryByText('関係の収集は無効です。'))).toBe(!enabled)
  })

  const center = {
    id: '11111111-1111-4111-8111-111111111111', name: 'lab', host: 'vc.example.local',
    protocol: 'https', port: 443, username: 'operator', is_enabled: false, verify_ssl: true,
    created_at: '2026-04-24T00:00:00Z',
  }
  const inventory = { enabled: true, interval_seconds: 300, timeout_seconds: 60, vcenters: [] }

  it.each([
    [null, true],
    ['2026-04-24T09:00:00+09:00', true],
    ['2026-04-24T00:05:00.123455Z', true],
    ['2026-04-24T00:05:00.123456Z', false],
    ['2026-04-24T00:10:00Z', false],
  ])('最後の成功が %s のとき、失敗中の表示は %s', async (success, failing) => {
    const error = '権限不足のため管理対象と関係を取得できませんでした。'.repeat(10)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({
          ...inventory,
          vcenters: [{
            vcenter_id: center.id, vcenter_name: center.name, is_enabled: center.is_enabled,
            first_success_at: success, last_started_at: '2026-04-24T00:05:00Z', last_success_at: success,
            last_failure_at: '2026-04-24T00:05:00.123456Z', last_error: error, last_warning: null, last_warning_at: null,
            object_count: null, relation_count: null,
          }],
        })
      : jsonResponse([center])))
    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    const detail = await screen.findByText(error)
    expect(detail).toHaveAttribute('title', error)
    const cell = detail.closest('td')!
    expect(within(cell).getByText('接続が無効のため収集しません')).toBeInTheDocument()
    if (failing) {
      expect(cell.textContent?.startsWith('失敗中')).toBe(true)
    } else {
      expect(within(cell).queryByText('失敗中')).not.toBeInTheDocument()
    }
  })

  it.each([false, true])('読み込み中と、収集状態の行がない場合や API が失敗した場合を区別する（失敗: %s）', async (fails) => {
    let finishStatus!: (response: Response) => void
    const status = new Promise<Response>((resolve) => { finishStatus = resolve })
    vi.stubGlobal('fetch', vi.fn((url: string) =>
      url === '/api/inventory/status' ? status : Promise.resolve(jsonResponse([{ ...center, is_enabled: true }])),
    ))
    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    const cell = (await screen.findByText('読み込み中…')).closest('td')!
    expect(cell).toHaveTextContent(/^読み込み中…$/)
    await act(async () => {
      finishStatus(fails ? jsonResponse({ detail: 'unavailable' }, 500) : jsonResponse(inventory))
    })
    expect(cell).toHaveTextContent(fails ? /^取得できません$/ : /^—$/)
    if (fails) expect(screen.getByRole('note')).toHaveTextContent('関係の収集状態を読み込めませんでした。')
    else expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('登録フォームでHTTPを選ぶとPOST payloadにprotocol=httpが含まれる', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse(inventory))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 'vc-1',
          name: 'lab',
          host: 'vc.example.local',
          protocol: 'http',
          port: 80,
          username: 'admin',
          is_enabled: true,
          verify_ssl: false,
          created_at: '2026-04-24T00:00:00Z',
        }, 201),
      )
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse(inventory))
    vi.stubGlobal('fetch', fetchMock)

    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/inventory/status', expect.any(Object))
    })

    fireEvent.change(screen.getByLabelText('表示名'), { target: { value: 'lab' } })
    fireEvent.change(screen.getByLabelText('ホスト'), { target: { value: 'vc.example.local' } })
    fireEvent.change(screen.getByLabelText('プロトコル'), { target: { value: 'http' } })
    fireEvent.change(screen.getByLabelText('ポート'), { target: { value: '80' } })
    fireEvent.change(screen.getByLabelText('ユーザー'), { target: { value: 'admin' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'secret' } })

    fireEvent.click(screen.getByRole('button', { name: '追加' }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/vcenters',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"protocol":"http"'),
        }),
      )
      expect(fetchMock.mock.calls.filter(([url]) => url === '/api/inventory/status')).toHaveLength(2)
    })
  })
})
