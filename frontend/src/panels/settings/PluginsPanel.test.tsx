import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { PluginsPanel } from './PluginsPanel'

const pluginResponse = {
  generation: 7,
  collectors: [
    {
      id: 'example.temperature',
      display_name: 'Temperature',
      source: 'entry_point:temperature',
      status: 'enabled',
      error: null,
      version: '2.1.0',
      api_version: 1,
      data_kinds: ['metric'],
      interval_seconds: 300,
      timeout_seconds: 45,
      runs: [
        {
          vcenter_id: '00000000-0000-0000-0000-000000000001',
          vcenter_name: 'Tokyo vCenter',
          status: 'ok',
          collector_version: '2.1.0',
          last_started_at: '2026-09-12T01:00:00Z',
          last_success_at: '2026-09-12T01:00:05Z',
          last_failure_at: null,
          events_inserted: 2,
          metrics_inserted: 3,
          error: null,
        },
      ],
    },
    {
      id: 'missing.collector',
      display_name: null,
      source: 'configuration',
      status: 'failed',
      error: 'configured plugin is not installed',
      version: null,
      api_version: null,
      data_kinds: [],
      interval_seconds: null,
      timeout_seconds: null,
      runs: [],
    },
  ],
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderPanel(onError = vi.fn()) {
  render(
    <TimeZoneProvider>
      <PluginsPanel onError={onError} />
    </TimeZoneProvider>,
  )
  return onError
}

describe('PluginsPanel', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
  })

  it('一覧を表示し、展開したプラグインの構成と vCenter 実行状態を表示する', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(pluginResponse)))

    renderPanel()

    expect(await screen.findByText('Temperature')).toBeInTheDocument()
    expect(screen.getByText('有効')).toHaveClass('plugin-status-badge--enabled')
    expect(screen.getByText('メトリクス')).toBeInTheDocument()
    expect(screen.getByText('外部')).toBeInTheDocument()
    expect(screen.getByText('レジストリ世代 7')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    expect(screen.getByText('entry_point:temperature')).toBeInTheDocument()
    expect(screen.getByText('Tokyo vCenter')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
    expect(screen.getByText('イベント 2 / メトリクス 3')).toBeInTheDocument()
    expect(screen.getByText(/10:00:05 AM/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Temperature の詳細を閉じる' }))
      .toHaveAttribute('aria-expanded', 'true')
  })

  it('構成エラーと実行記録の空状態を展開表示する', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(pluginResponse)))

    renderPanel()
    await screen.findByText('missing.collector')
    fireEvent.click(screen.getByRole('button', { name: 'missing.collector の詳細を開く' }))

    expect(screen.getByText(/configured plugin is not installed/)).toBeInTheDocument()
    expect(screen.getByText('実行記録はありません。')).toBeInTheDocument()
  })

  it('手動更新中はボタンを無効化し、失敗しても取得済み一覧を保持する', async () => {
    let rejectRefresh: ((reason?: unknown) => void) | undefined
    const refresh = new Promise<Response>((_resolve, reject) => {
      rejectRefresh = reject
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(pluginResponse))
      .mockReturnValueOnce(refresh)
    vi.stubGlobal('fetch', fetchMock)
    const onError = renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: '一覧を更新' }))
    expect(screen.getByRole('button', { name: '更新中…' })).toBeDisabled()
    expect(screen.getByText('Temperature')).toBeInTheDocument()

    rejectRefresh?.(new Error('refresh failed'))
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith('refresh failed'))
    expect(screen.getByText('Temperature')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '一覧を更新' })).toBeEnabled()
  })

  it('不正なレスポンスをエラーとして扱う', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ collectors: [] })))
    const onError = renderPanel()

    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining('generation')))
    expect(screen.getByText('プラグインは登録されていません。')).toBeInTheDocument()
  })
})
