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
    <AuthContext.Provider value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout: async () => {} }}>
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
        if (url.includes('/api/event-score-rules')) return Promise.resolve(jsonResponse([]))
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

  it('viewer にはサーバ保存の設定を閲覧専用で見せる', async () => {
    renderAs('viewer')
    await openSettings('スコアルール')
    expect(await screen.findByRole('note')).toHaveTextContent('閲覧のみです')
    const fieldset = document.querySelector('fieldset.readonly-fieldset')
    expect(fieldset).toBeDisabled()
  })

  it('ブラウザに保存する設定（一般）は viewer でも編集できる', async () => {
    renderAs('viewer')
    await openSettings('一般')
    await screen.findByText((content, el) => el?.tagName === 'P' && content.includes('このブラウザで使う基本設定'))
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    expect(document.querySelector('fieldset.readonly-fieldset')).toBeNull()
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

  it('admin には閲覧専用の表示を出さない', async () => {
    renderAs('admin')
    await openSettings('vCenter')
    expect(await screen.findByRole('button', { name: '編集' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '追加' })).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('ヘッダーに利用者名とロールを出す（ディレクトリの利用者にはパスワード変更を出さない）', async () => {
    renderAs('operator', { display_name: 'Olivia', can_change_password: false })
    expect(await screen.findByText('Olivia')).toBeInTheDocument()
    expect(screen.getByText('オペレーター')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'ログアウト' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'パスワード変更' })).not.toBeInTheDocument()
  })

  it('認証が無効なサーバではユーザーメニューを出さない', async () => {
    renderAs('admin', { auth_enabled: false })
    await screen.findByRole('heading', { name: 'vCenter Event Assistant' })
    expect(screen.queryByRole('button', { name: 'ログアウト' })).not.toBeInTheDocument()
  })
})
