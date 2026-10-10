/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Me, Role } from './api/schemas'
import { AuthContext } from './auth/authContext'
import { roleAtLeast } from './auth/roles'

vi.mock('./panels/metrics/MetricsPanel', () => ({ MetricsPanel: () => <div /> }))

import App from './App'

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

const VCENTER = {
  id: 'vc-1',
  name: 'vc-lab',
  host: 'vc.example.com',
  protocol: 'https',
  port: 443,
  username: 'reader',
  verify_ssl: true,
  is_enabled: true,
  created_at: '2026-01-01T00:00:00Z',
}

const ALERT_RULE = {
  id: 7,
  name: '高スコアイベント',
  rule_type: 'event_score',
  is_enabled: true,
  alert_level: 'warning',
  config: { threshold: 60, cooldown_minutes: 45 },
  created_at: '2026-01-01T00:00:00Z',
}

const refresh = async () => {}

function renderAs(role: Role, overrides: Partial<Me> = {}) {
  const me: Me = {
    auth_enabled: true,
    username: `${role}-user`,
    display_name: null,
    role,
    realm: 'local',
    can_change_password: true,
    ...overrides,
  }
  return render(
    <AuthContext.Provider value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout: async () => {}, refresh }}>
      <App />
    </AuthContext.Provider>,
  )
}

function mainNav(): HTMLElement {
  const el = document.querySelector('nav.tabs')
  if (!el) throw new Error('nav.tabs not found')
  return el as HTMLElement
}

async function openSettings(label: string) {
  fireEvent.click(within(mainNav()).getByRole('button', { name: '設定' }))
  const subNav = await screen.findByRole('navigation', { name: '設定' })
  fireEvent.click(within(subNav).getByRole('button', { name: label }))
}

describe('App のロールによる出し分け', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/')
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/config')) {
          return Promise.resolve(
            jsonResponse({ event_retention_days: 7, metric_retention_days: 7, perf_sample_interval_seconds: 300 }),
          )
        }
        if (url.includes('/api/vcenters')) return Promise.resolve(jsonResponse([VCENTER]))
        if (url.includes('/api/event-score-rules')) {
          return Promise.resolve(jsonResponse([{ id: 1, event_type: 'vim.event.VmPoweredOnEvent', score_delta: 10 }]))
        }
        if (url.includes('/api/alerts/rules')) return Promise.resolve(jsonResponse([ALERT_RULE]))
        if (url.includes('/api/auth/users')) return Promise.resolve(jsonResponse([]))
        if (url.includes('/api/auth/directories/policy')) {
          return Promise.resolve(jsonResponse({ allow_insecure_tls: true, allow_no_transport_security: true }))
        }
        if (url.includes('/api/auth/directories')) return Promise.resolve(jsonResponse([]))
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('viewer にはチャットタブを出さず、URL で開いても概要に戻す', async () => {
    window.history.replaceState(null, '', '/#/chat')
    renderAs('viewer')
    await waitFor(() => expect(window.location.hash).toBe('#/summary'))
    expect(within(mainNav()).queryByRole('button', { name: 'チャット' })).not.toBeInTheDocument()
    expect(within(mainNav()).getByRole('button', { name: '概要' })).toHaveClass('active')
  })

  it('operator にはチャットタブを出す', async () => {
    renderAs('operator')
    expect(await within(mainNav()).findByRole('button', { name: 'チャット' })).toBeInTheDocument()
  })

  it('viewer にはサーバ保存の設定を閲覧専用で見せ、エクスポートも出さない', async () => {
    renderAs('viewer')
    await openSettings('スコアルール')
    expect(await screen.findByRole('note')).toHaveTextContent('閲覧のみです')
    expect(await screen.findByText('vim.event.VmPoweredOnEvent')).toBeInTheDocument()
    expect(screen.getByLabelText('vim.event.VmPoweredOnEvent の加算')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'ファイルにエクスポート' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'エクスポート' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ファイルからインポート' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '追加' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
  })

  it('アラートルールは viewer でも行を展開して詳細（再通知間隔）を確認できる', async () => {
    renderAs('viewer')
    await openSettings('アラート')
    fireEvent.click(await screen.findByRole('button', { name: '高スコアイベント の詳細を開く' }))
    const cooldown = await screen.findByLabelText(/高スコアイベント の再通知間隔/)
    expect(cooldown).toHaveValue(45)
    expect(cooldown).toHaveAttribute('readonly')
    expect(screen.getByLabelText('高スコアイベント のアラートレベル')).toBeDisabled()
    expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '追加' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '追加' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ファイルにエクスポート' })).not.toBeInTheDocument()
  })

  it.each(['スコアルール', 'イベント種別ガイド', 'アラート'])(
    '%s のファイルへのエクスポートは operator 以上にだけ出す（インポートは admin だけ）',
    async (label) => {
      const { unmount } = renderAs('viewer')
      await openSettings(label)
      expect(await screen.findByRole('note')).toHaveTextContent('閲覧のみです')
      expect(screen.queryByRole('button', { name: 'ファイルにエクスポート' })).not.toBeInTheDocument()
      unmount()

      renderAs('operator')
      await openSettings(label)
      expect(await screen.findByRole('button', { name: 'ファイルにエクスポート' })).toBeEnabled()
      expect(screen.getByRole('heading', { name: 'エクスポート' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'ファイルからインポート' })).not.toBeInTheDocument()
    },
  )

  it('ブラウザに保存する設定（一般）は viewer でも編集できる', async () => {
    renderAs('viewer')
    await openSettings('一般')
    await screen.findByText((content, el) => el?.tagName === 'P' && content.includes('このブラウザで使用する基本設定'))
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('vCenter は viewer に操作ボタンを出さず、operator には接続テストだけ出す', async () => {
    const { unmount } = renderAs('viewer')
    await openSettings('vCenter')
    expect(await screen.findByText('vc-lab')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接続テスト' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '編集' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '追加' })).not.toBeInTheDocument()
    unmount()

    renderAs('operator')
    await openSettings('vCenter')
    expect(await screen.findByRole('button', { name: '接続テスト' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '編集' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
  })

  it('ユーザー管理は admin にだけ出し、ほかのロールが URL で開いても一般に戻す', async () => {
    window.history.replaceState(null, '', '/#/settings/users')
    const { unmount } = renderAs('operator')
    await waitFor(() => expect(window.location.hash).toBe('#/settings/general'))
    const subNav = await screen.findByRole('navigation', { name: '設定' })
    expect(within(subNav).queryByRole('button', { name: 'ユーザー' })).not.toBeInTheDocument()
    unmount()

    window.history.replaceState(null, '', '/#/settings/users')
    renderAs('admin')
    expect(await screen.findByRole('heading', { name: 'ローカルユーザーの作成' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/settings/users')
  })

  it('認証ディレクトリは admin にだけ出し、ほかのロールが URL で開いても一般に戻す', async () => {
    window.history.replaceState(null, '', '/#/settings/directories')
    const { unmount } = renderAs('operator')
    await waitFor(() => expect(window.location.hash).toBe('#/settings/general'))
    const subNav = await screen.findByRole('navigation', { name: '設定' })
    expect(within(subNav).queryByRole('button', { name: '認証ディレクトリ' })).not.toBeInTheDocument()
    unmount()

    window.history.replaceState(null, '', '/#/settings/directories')
    renderAs('admin')
    expect(await screen.findByRole('button', { name: 'ディレクトリを追加' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/settings/directories')
  })

  it('認証が無効なサーバではユーザー管理と認証ディレクトリを出さない', async () => {
    renderAs('admin', { auth_enabled: false })
    fireEvent.click(within(mainNav()).getByRole('button', { name: '設定' }))
    const subNav = await screen.findByRole('navigation', { name: '設定' })
    expect(within(subNav).queryByRole('button', { name: 'ユーザー' })).not.toBeInTheDocument()
    expect(within(subNav).queryByRole('button', { name: '認証ディレクトリ' })).not.toBeInTheDocument()
  })

  it('admin には閲覧専用の表示を出さない', async () => {
    renderAs('admin')
    await openSettings('vCenter')
    expect(await screen.findByRole('button', { name: '編集' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '追加' })).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('ヘッダーのアバターから利用者名とロールを出す（ディレクトリの利用者にはパスワード変更を出さない）', async () => {
    renderAs('operator', { display_name: 'Olivia', can_change_password: false })
    const avatar = await screen.findByRole('button', { name: 'アカウントメニュー（Olivia・オペレーター）' })
    fireEvent.click(avatar)
    const menu = screen.getByRole('menu', { name: 'アカウント' })
    expect(within(menu).getByText('Olivia')).toBeInTheDocument()
    expect(within(menu).getByText('オペレーター')).toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: 'ログアウト' })).toBeInTheDocument()
    expect(within(menu).queryByRole('menuitem', { name: 'パスワード変更' })).not.toBeInTheDocument()
  })

  it('認証が無効なサーバではユーザーメニューを出さない', async () => {
    renderAs('admin', { auth_enabled: false })
    await screen.findByRole('heading', { name: 'vCenter Event Assistant' })
    expect(screen.queryByRole('button', { name: /アカウントメニュー/ })).not.toBeInTheDocument()
  })
})
