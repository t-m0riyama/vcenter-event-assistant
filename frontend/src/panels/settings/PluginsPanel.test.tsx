import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, AUTH_DISABLED_ME } from '../../auth/authContext'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { PluginsPanel } from './PluginsPanel'

const pluginResponse = {
  generation: 7,
  collectors: [
    {
      id: 'example.temperature',
      display_name: 'Temperature',
      description: 'ホストの温度を集めるサンプル。',
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

    expect(screen.getByText('ホストの温度を集めるサンプル。')).toBeInTheDocument()
    expect(screen.getByText('entry_point:temperature')).toBeInTheDocument()
    expect(screen.getByText('Tokyo vCenter')).toBeInTheDocument()
    expect(screen.getByText('成功')).toBeInTheDocument()
    expect(screen.getByText('イベント 2 / メトリクス 3 / ログ 0')).toBeInTheDocument()
    expect(screen.getByText(/10:00:05 AM/)).toBeInTheDocument()
    const table = screen.getByRole('columnheader', { name: 'エラー' }).closest('table')!
    expect(within(table).getByRole('columnheader', { name: '成功日時' })).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: '失敗日時' })).toBeInTheDocument()
    const cells = within(table).getAllByRole('cell')
    expect(cells[5]).toHaveTextContent(/^—$/)
    expect(cells[7]).toHaveTextContent(/^—$/)
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
    // 応答に description が無くてもパースは通り、説明の段落は出ない。
    expect(document.querySelector('.plugin-description')).toBeNull()
  })

  it.each([
    { success: null, status: 'failed', error: 'vim.fault.InvalidLogin: collector execution failed', label: '失敗中' },
    { success: '2026-09-12T01:00:04Z', status: 'failed', error: 'vim.fault.InvalidLogin: collector execution failed', label: '失敗中' },
    { success: '2026-09-12T01:00:06Z', status: 'ok', error: 'vim.fault.InvalidLogin: collector execution failed', label: '過去の失敗' },
    { success: '2026-09-12T01:00:06Z', status: 'ok', error: null, label: '過去の失敗' },
    { success: '2026-09-12T01:00:04Z', status: 'running', error: null, label: '失敗中' },
  ] as const)('状態が $status、成功時刻が $success、エラーが $error の実行記録は $label と表示する', async ({ success, status, error, label }) => {
    const collector = pluginResponse.collectors[0]
    const run = { ...collector.runs[0], status, last_success_at: success, last_failure_at: '2026-09-12T01:00:05Z', error }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...pluginResponse, collectors: [{ ...collector, runs: [run] }],
    })))

    renderPanel()
    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    const row = screen.getByText('Tokyo vCenter').closest('tr')!
    expect(within(row).getByText({ ok: '成功', failed: '失敗', running: '実行中' }[status])).toBeInTheDocument()
    expect(within(row).getByText(label)).toBeInTheDocument()
    expect(within(row).queryByText(label === '失敗中' ? '過去の失敗' : '失敗中')).not.toBeInTheDocument()
    if (label === '過去の失敗' && success) {
      expect(within(row).getByText(/この後、/))
        .toHaveTextContent(`この後、${formatIsoInTimeZone(success, 'Asia/Tokyo')} に成功しています`)
    } else {
      expect(within(row).queryByText(/この後、/)).not.toBeInTheDocument()
    }
    if (error) {
      expect(within(row).getByText('認証または権限の問題で収集できませんでした。ユーザー名、パスワード、接続先での権限を確認してください。（種類: vim.fault.InvalidLogin）')).toBeInTheDocument()
      const summary = within(row).getByText('詳細')
      expect(summary).toHaveAccessibleName('詳細（Tokyo vCenter のエラー）')
      const details = summary.closest('details')!
      expect(details).not.toHaveAttribute('open')
      expect(within(details).getByText(error)).toBeInTheDocument()
      expect(within(row).getAllByText(error)).toEqual([within(details).getByText(error)])
    } else {
      expect(within(row).queryByText('詳細')).not.toBeInTheDocument()
    }
  })

  it('成功と失敗が同時刻でエラー本文がなければ、エラー欄に「—」を表示する', async () => {
    const collector = pluginResponse.collectors[0]
    const run = { ...collector.runs[0], last_failure_at: '2026-09-12T10:00:05+09:00' }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...pluginResponse, collectors: [{ ...collector, runs: [run] }],
    })))
    renderPanel()
    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    const row = screen.getByText('Tokyo vCenter').closest('tr')!
    expect(within(row).getAllByRole('cell')[7]).toHaveTextContent(/^—$/)
  })

  it('失敗時刻がなくても、エラー本文があれば案内と名前付きの詳細を表示する', async () => {
    const collector = pluginResponse.collectors[0]
    const error = 'worker exited before responding: collector execution failed'
    const run = { ...collector.runs[0], last_success_at: null, error }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      ...pluginResponse, collectors: [{ ...collector, runs: [
        run, { ...run, vcenter_id: 'osaka', vcenter_name: 'Osaka vCenter' },
      ] }],
    })))
    renderPanel()
    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    for (const name of ['Tokyo vCenter', 'Osaka vCenter']) {
      const row = screen.getByText(name).closest('tr')!
      const cell = within(row).getAllByRole('cell')[7]
      expect(within(cell).getByText('収集を実行するプロセスが異常終了したか、利用できません。続く場合は管理者に連絡してください。（種類: worker exited before responding）')).toBeInTheDocument()
      expect(cell).not.toHaveTextContent(/失敗中|過去の失敗/)
      const summary = within(cell).getByText('詳細')
      expect(summary).toHaveAccessibleName(`詳細（${name} のエラー）`)
      expect(within(summary.closest('details')!).getByText(error)).toBeInTheDocument()
    }
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

const managedResponse = {
  ...pluginResponse,
  management_enabled: true,
  reload_required: false,
  collectors: pluginResponse.collectors.map((collector) => ({
    ...collector,
    env_locked_fields: [],
  })),
}

const installedResponse = {
  management_enabled: true,
  index_install_enabled: false,
  plugins: [
    {
      distribution: 'example-collector',
      version: '0.1.0',
      source: 'upload',
      origin: 'example_collector-0.1.0-py3-none-any.whl',
      status: 'installed',
      error: null,
      installed_at: '2026-09-12T01:00:00Z',
    },
  ],
}

/** URL とメソッドでルーティングする fetch スタブ。 */
function routedFetch(routes: Record<string, unknown>, onCall?: (url: string, init?: RequestInit) => void) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    onCall?.(url, init)
    const key = `${init?.method ?? 'GET'} ${url}`
    if (key in routes) return jsonResponse(routes[key])
    if (url in routes) return jsonResponse(routes[url])
    throw new Error(`unexpected request: ${key}`)
  })
}

describe('PluginsPanel（プラグイン管理が有効なとき）', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
  })

  it('管理が無効なときは編集 UI を出さず、従来の案内を表示する', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(pluginResponse)))
    renderPanel()

    await screen.findByText('Temperature')
    expect(screen.getByText(/アプリの再起動が必要です/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '変更を反映' })).not.toBeInTheDocument()
    expect(screen.queryByText('インストール済みプラグイン')).not.toBeInTheDocument()
  })

  it('admin 以外には管理系の API を呼ばず、一覧と実行状況だけを見せる', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      routedFetch({ '/api/plugins/collectors': managedResponse }, (url) => urls.push(url)),
    )
    const onError = vi.fn()
    render(
      <AuthContext.Provider
        value={{ me: { ...AUTH_DISABLED_ME, auth_enabled: true, role: 'operator' }, hasRole: (r) => r !== 'admin', logout: async () => {} }}
      >
        <TimeZoneProvider>
          <PluginsPanel onError={onError} />
        </TimeZoneProvider>
      </AuthContext.Provider>,
    )

    await screen.findByText('Temperature')
    expect(screen.getByText(/設定の変更とパッケージの追加は管理者が行います/)).toBeInTheDocument()
    expect(urls).not.toContain('/api/plugins/installed')
    expect(screen.queryByRole('button', { name: '変更を反映' })).not.toBeInTheDocument()
    expect(screen.queryByText('インストール済みプラグイン')).not.toBeInTheDocument()
    // 詳細（実行状況）は開ける
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))
    expect(await screen.findByText('Tokyo vCenter')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '設定を始める' })).not.toBeInTheDocument()
    expect(onError).not.toHaveBeenCalledWith(expect.stringContaining('権限'))
  })

  it('チェックを変えただけでは保存せず、未保存であることを知らせる', async () => {
    const calls: Array<unknown> = []
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': managedResponse,
          '/api/plugins/installed': installedResponse,
        },
        (_url, init) => {
          if (init?.method === 'PATCH') calls.push(init.body)
        },
      ),
    )
    renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    // 変更がないあいだは保存できない。
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()

    fireEvent.click(screen.getByLabelText('有効にする'))

    expect(screen.getByText('未保存の変更があります。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled()
    expect(calls).toHaveLength(0)
  })

  it('保存で PATCH を送り、未反映バナーを表示する', async () => {
    const patched = {
      ...managedResponse, reload_required: true,
      collectors: managedResponse.collectors.map(collector => collector.id === 'example.temperature'
        ? { ...collector, status: 'disabled' } : collector),
    }
    const calls: Array<{ url: string; body: unknown }> = []
    const fetchMock = routedFetch(
      {
        '/api/plugins/collectors': managedResponse,
        '/api/plugins/installed': installedResponse,
        'PATCH /api/plugins/collectors/example.temperature': patched,
      },
      (url, init) => {
        if (init?.method === 'PATCH') {
          calls.push({ url, body: JSON.parse(String(init.body)) })
        }
      },
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))
    fireEvent.click(screen.getByLabelText('有効にする'))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]?.url).toBe('/api/plugins/collectors/example.temperature')
    expect(calls[0]?.body).toEqual({
      enabled: false,
      interval_seconds: 300,
      timeout_seconds: 45,
    })
    expect(await screen.findByText(/未反映の変更があります/)).toBeInTheDocument()
    expect(screen.getByLabelText('有効にする')).not.toBeChecked()
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(screen.queryByText('未保存の変更があります。')).not.toBeInTheDocument()
    // 未反映のあいだは、次に押すべきボタンとして強調する。
    expect(screen.getByRole('button', { name: '変更を反映' })).toHaveClass('btn--filled')
  })

  it('実行間隔の保存で PATCH に数値を送る', async () => {
    const calls: Array<unknown> = []
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': managedResponse,
          '/api/plugins/installed': installedResponse,
          'PATCH /api/plugins/collectors/example.temperature': managedResponse,
        },
        (_url, init) => {
          if (init?.method === 'PATCH') calls.push(JSON.parse(String(init.body)))
        },
      ),
    )
    renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))
    fireEvent.change(screen.getByLabelText('実行間隔（秒）'), { target: { value: '600' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({ enabled: true, interval_seconds: 600, timeout_seconds: 45 })
  })

  it('環境変数でロックされた項目は編集できない', async () => {
    const locked = {
      ...managedResponse,
      collectors: [
        { ...managedResponse.collectors[0], env_locked_fields: ['enabled', 'interval_seconds'] },
        managedResponse.collectors[1],
      ],
    }
    const calls: Array<unknown> = []
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': locked,
          '/api/plugins/installed': installedResponse,
          'PATCH /api/plugins/collectors/example.temperature': locked,
        },
        (_url, init) => {
          if (init?.method === 'PATCH') calls.push(JSON.parse(String(init.body)))
        },
      ),
    )
    renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: 'Temperature の詳細を開く' }))

    expect(screen.getByLabelText('有効にする')).toBeDisabled()
    expect(screen.getByLabelText('実行間隔（秒）')).toBeDisabled()
    expect(screen.getByLabelText('タイムアウト（秒）')).toBeEnabled()
    expect(screen.getAllByText(/環境変数で固定されているため/).length).toBeGreaterThan(0)

    // ロックされた項目は保存対象から外れる。
    fireEvent.change(screen.getByLabelText('タイムアウト（秒）'), { target: { value: '60' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({ timeout_seconds: 60 })
  })

  it('「変更を反映」で reload を呼び、新しい世代を知らせる', async () => {
    const reloaded = {
      generation: 8,
      jobs_added: [],
      jobs_removed: ['poll_events'],
      jobs_rescheduled: [],
      collectors: managedResponse.collectors,
    }
    const methods: string[] = []
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': { ...managedResponse, generation: 8 },
          '/api/plugins/installed': installedResponse,
          'POST /api/plugins/collectors/reload': reloaded,
        },
        (url, init) => methods.push(`${init?.method ?? 'GET'} ${url}`),
      ),
    )
    renderPanel()

    await screen.findByText('Temperature')
    fireEvent.click(screen.getByRole('button', { name: '変更を反映' }))

    expect(await screen.findByText('レジストリを世代 8 に更新しました。')).toBeInTheDocument()
    expect(methods).toContain('POST /api/plugins/collectors/reload')
    // リロード後は一覧を取り直す。
    expect(methods.filter((m) => m === 'GET /api/plugins/collectors').length).toBeGreaterThan(1)
  })

  it('インストール済み一覧を表示し、アップロードで multipart を送る', async () => {
    let uploadedBody: unknown = null
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': managedResponse,
          '/api/plugins/installed': installedResponse,
          'POST /api/plugins/installed/upload': installedResponse,
        },
        (url, init) => {
          if (url.endsWith('/upload')) uploadedBody = init?.body
        },
      ),
    )
    renderPanel()

    expect(await screen.findByText('インストール済みプラグイン')).toBeInTheDocument()
    expect(screen.getByText('example-collector')).toBeInTheDocument()
    expect(screen.getByText('インストール済み')).toBeInTheDocument()
    // インデックスインストールが無効なら requirement 入力は出さない。
    expect(screen.queryByLabelText('インデックスから追加')).not.toBeInTheDocument()

    const file = new File(['wheel'], 'example_collector-0.1.0-py3-none-any.whl')
    fireEvent.change(screen.getByLabelText('パッケージ（.whl / .tar.gz）を追加'), {
      target: { files: [file] },
    })

    await waitFor(() => expect(uploadedBody).toBeInstanceOf(FormData))
    expect((uploadedBody as FormData).get('file')).toBe(file)
    expect(await screen.findByText('インストールを開始しました。')).toBeInTheDocument()
  })

  it('インデックスインストールが有効なときだけ requirement 入力を出す', async () => {
    vi.stubGlobal(
      'fetch',
      routedFetch({
        '/api/plugins/collectors': managedResponse,
        '/api/plugins/installed': { ...installedResponse, index_install_enabled: true },
      }),
    )
    renderPanel()

    expect(await screen.findByLabelText('インデックスから追加')).toBeInTheDocument()
  })

  it('確認ダイアログを承諾したときだけアンインストールする', async () => {
    const methods: string[] = []
    vi.stubGlobal(
      'fetch',
      routedFetch(
        {
          '/api/plugins/collectors': managedResponse,
          '/api/plugins/installed': installedResponse,
          'DELETE /api/plugins/installed/example-collector': installedResponse,
        },
        (url, init) => methods.push(`${init?.method ?? 'GET'} ${url}`),
      ),
    )
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPanel()

    await screen.findByText('example-collector')
    fireEvent.click(screen.getByRole('button', { name: '削除' }))
    expect(methods).not.toContain('DELETE /api/plugins/installed/example-collector')

    confirmSpy.mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: '削除' }))
    await waitFor(() =>
      expect(methods).toContain('DELETE /api/plugins/installed/example-collector'),
    )
    confirmSpy.mockRestore()
  })
})
