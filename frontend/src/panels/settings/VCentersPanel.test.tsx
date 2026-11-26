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
          enabled, config_enabled: enabled, interval_seconds: 300, timeout_seconds: 60,
          vcenters: [{
            vcenter_id: id, vcenter_name: 'lab', is_enabled: true, first_success_at: at,
            last_started_at: failure, last_success_at: at, last_failure_at: failure,
            last_error: 'NoPermission: 権限不足', last_warning: '関係の件数が急減', last_warning_at: warning,
            object_count: 0, relation_count: 21,
          }],
        })
      : jsonResponse([{
          id, name: 'lab', host: 'vc.example.local', protocol: 'https', port: 443, username: 'operator',
          is_enabled: true, verify_ssl: true, created_at: at,
        }])))

    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    expect(await screen.findByText(/接続先での権限を確認してください。権限不足（種類: NoPermission）/)).toBeInTheDocument()
    expect(screen.getByText('関係の件数が急減')).toBeInTheDocument()
    for (const time of [at, failure, warning]) {
      expect(screen.getByText(formatIsoInTimeZone(time, zone))).toBeInTheDocument()
    }
    expect(screen.getByText('最後の成功')).toBeInTheDocument()
    expect(screen.getByText('最後の失敗')).toBeInTheDocument()
    expect(screen.getByText(/管理対象 0 件、関係 21 件/)).toBeInTheDocument()
    expect(Boolean(screen.queryByText('関係の収集は無効です。'))).toBe(!enabled)
  })

  const center = {
    id: '11111111-1111-4111-8111-111111111111', name: 'lab', host: 'vc.example.local',
    protocol: 'https', port: 443, username: 'operator', is_enabled: false, verify_ssl: true,
    created_at: '2026-04-24T00:00:00Z',
  }
  const inventory = { enabled: true, config_enabled: true, interval_seconds: 300, timeout_seconds: 60, vcenters: [] }

  it.each([
    [true, '2026-04-24T00:00:00Z', '失敗中'],
    [true, '2026-04-24T00:10:00Z', '過去の失敗'],
    [false, '2026-04-24T00:00:00Z', '無効（スケジューラ、関係の収集、または構成の読み取りが無効のため収集しません）'],
  ])('構成の読み取りの状態を表示する（有効: %s、最後の成功: %s）', async (enabled, success, label) => {
    const failure = '2026-04-24T00:05:00Z'
    const warning = '2026-04-24T00:06:00Z'
    const error = 'ConfigReadTimeout: 構成の読み取りがタイムアウトしました。'
    const zone = 'UTC'
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, zone)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({
          ...inventory, config_enabled: enabled,
          vcenters: [{
            vcenter_id: center.id, vcenter_name: center.name, is_enabled: true,
            first_success_at: null, last_started_at: null, last_success_at: null, last_failure_at: null,
            last_error: null, last_warning: null, last_warning_at: null, object_count: null, relation_count: null,
            config_last_success_at: success, config_last_failure_at: failure, config_last_error: error,
            config_last_warning: '構成の差分が多数あります。', config_last_warning_at: warning, config_deferred_count: 0,
          }],
        })
      : jsonResponse([{ ...center, is_enabled: true }])))
    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    const section = within(await screen.findByRole('group', { name: '構成の読み取り' }))
    expect(section.getByText(label)).toBeInTheDocument()
    expect(section.queryByText(label === '失敗中' ? '過去の失敗' : '失敗中')).not.toBeInTheDocument()
    expect(section.getByText('最後の成功')).toHaveTextContent(formatIsoInTimeZone(success, zone))
    expect(section.getByText('最後の失敗')).toHaveTextContent(formatIsoInTimeZone(failure, zone))
    expect(section.getByText('警告')).toHaveTextContent(formatIsoInTimeZone(warning, zone))
    expect(section.getByText('構成の差分が多数あります。')).toBeInTheDocument()
    expect(section.getByText('読み残した VM 0 台')).toBeInTheDocument()
    if (label === '過去の失敗') expect(section.getByText(/この後、/)).toHaveTextContent(formatIsoInTimeZone(success, zone))
    expect(section.getByText(/INVENTORY_SYNC_TIMEOUT_SECONDS/)).toBeInTheDocument()
    const summary = section.getByText('詳細')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(within(details).getByText(error)).toBeInTheDocument()
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
  })

  it.each([
    ['InventoryReadsClosed', 'インベントリの読み取り受付は終了しました。', '収集が再開しない場合は管理者に連絡してください。'],
    ['InventoryReadTimeout', '読み取りがタイムアウトしました。', 'インベントリの収集のタイムアウト設定（INVENTORY_SYNC_TIMEOUT_SECONDS）'],
    ['InventoryReadStillRunning', '前回の読み取りがまだ実行中です。', '次の収集で自動的にやり直します。'],
    ['InventoryWorkerUnavailable', '専用スレッドに空きがありません。', '次の収集で自動的にやり直します。'],
  ])('%s の案内は関係と構成の両方に出る', async (type, detail, guidance) => {
    const error = `${type}: ${detail}`
    const failure = center.created_at
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({ ...inventory, vcenters: [{
        vcenter_id: center.id, vcenter_name: center.name, is_enabled: true, first_success_at: null,
        last_started_at: null, last_success_at: null, last_failure_at: failure, last_error: error,
        last_warning: null, last_warning_at: null, object_count: null, relation_count: null,
        config_last_failure_at: failure, config_last_error: error, config_deferred_count: null,
      }] })
      : jsonResponse([{ ...center, is_enabled: true }])))
    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    for (const name of ['関係の収集', '構成の読み取り']) {
      const group = within(await screen.findByRole('group', { name }))
      expect(await group.findByText(new RegExp(`種類: ${type}`))).toHaveTextContent(guidance)
      expect(group.getByText('失敗中')).toBeInTheDocument()
    }
    expect(within(screen.getByRole('group', { name: '構成の読み取り' })).queryByText(/読み残した VM/)).not.toBeInTheDocument()
  })

  it.each([true, false])('構成の状態は一覧より状態 API の接続設定を優先する（有効: %s）', async (enabled) => {
    const failure = center.created_at
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({ ...inventory, vcenters: [{
        vcenter_id: center.id, vcenter_name: center.name, is_enabled: enabled, first_success_at: null,
        last_started_at: null, last_success_at: null, last_failure_at: null, last_error: null,
        last_warning: null, last_warning_at: null, object_count: null, relation_count: null,
        config_last_failure_at: failure,
      }] })
      : jsonResponse([{ ...center, is_enabled: !enabled }])))
    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    const group = within(await screen.findByRole('group', { name: '構成の読み取り' }))
    if (enabled) {
      expect(group.getByText('失敗中')).toBeInTheDocument()
      expect(group.queryByText(/接続が無効/)).not.toBeInTheDocument()
    } else {
      expect(group.getByText('無効（接続が無効のため収集しません）')).toBeInTheDocument()
      expect(group.queryByText('失敗中')).not.toBeInTheDocument()
    }
  })

  it('成功も失敗もない接続の収集状態を未収集と表示する', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/inventory/status'
      ? jsonResponse({
          ...inventory,
          vcenters: [{
            vcenter_id: center.id, vcenter_name: center.name, is_enabled: true,
            first_success_at: null, last_started_at: null, last_success_at: null,
            last_failure_at: null, last_error: null, last_warning: null, last_warning_at: null,
            object_count: null, relation_count: null,
          }],
        })
      : jsonResponse([{ ...center, is_enabled: true }])))

    render(<TimeZoneProvider><VCentersPanel onError={vi.fn()} /></TimeZoneProvider>)
    const relation = within(await screen.findByRole('group', { name: '関係の収集' }))
    expect(await relation.findByText('最後の成功 未収集')).toBeInTheDocument()
    expect(relation.getByText('管理対象 — 件、関係 — 件')).toBeInTheDocument()
    expect(relation.queryByText(/最後の失敗|失敗中|警告/)).not.toBeInTheDocument()
  })

  it.each([
    [null, '失敗中'],
    ['2026-04-24T09:00:00+09:00', '失敗中'],
    ['2026-04-24T00:05:00.123455Z', '失敗中'],
    ['2026-04-24T09:05:00.123456+09:00', null],
    ['2026-04-24T09:05:00.123457+09:00', '過去の失敗'],
    ['2026-04-24T00:10:00Z', '過去の失敗'],
  ])('最後の成功が %s のとき、失敗の表示を %s にする', async (success, label) => {
    const error = 'AttributeError: collector execution failed'
    const zone = 'Asia/Tokyo'
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, zone)
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
    const message = await screen.findByText('アプリまたはプラグインの内部エラーの可能性があります。設定を確かめても直らなければ、管理者に連絡してください。（種類: AttributeError）')
    const cell = message.closest('[role=group]')!
    expect(within(cell).getByText('接続が無効のため収集しません')).toBeInTheDocument()
    expect(Boolean(within(cell).queryByText('失敗中'))).toBe(label === '失敗中')
    if (label === '失敗中') {
      expect(cell.textContent?.startsWith('失敗中')).toBe(true)
    }
    const pastFailure = within(cell).queryByText('過去の失敗')
    expect(Boolean(pastFailure)).toBe(label === '過去の失敗')
    if (label === '過去の失敗' && success) {
      expect(pastFailure?.parentElement).toHaveClass('collection-failure--past')
      expect(within(cell).getByText(/この後、/)).toHaveTextContent(`この後、${formatIsoInTimeZone(success, zone)} に成功しています`)
    } else {
      expect(within(cell).queryByText(/この後、/)).not.toBeInTheDocument()
    }
    const summary = within(cell).getByText('詳細')
    expect(summary).toHaveAccessibleName('詳細（lab のエラー）')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(within(details).getByText(error)).toBeInTheDocument()
    expect(within(cell).getAllByText(error)).toEqual([within(details).getByText(error)])
    expect(message).not.toHaveAttribute('title')
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
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
    expect(within(cell).getByRole('group', { name: '関係の収集' })).toHaveTextContent(fails ? /^取得できません$/ : /^—$/)
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
