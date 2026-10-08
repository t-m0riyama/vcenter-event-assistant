/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ManagedUser, Me } from '../../api/schemas'
import { AuthContext } from '../../auth/authContext'
import { roleAtLeast } from '../../auth/roles'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { UsersPanel } from './UsersPanel'

const SELF_ID = '00000000-0000-0000-0000-000000000001'

const ME: Me = {
  auth_enabled: true,
  username: 'admin',
  display_name: null,
  role: 'admin',
  realm: 'local',
  can_change_password: true,
  principal_id: `${SELF_ID}:session-1`,
}

function user(overrides: Partial<ManagedUser>): ManagedUser {
  return {
    id: SELF_ID,
    username: 'admin',
    display_name: null,
    email: null,
    role: 'admin',
    realm: 'local',
    is_local: true,
    is_active: true,
    locked: false,
    locked_until: null,
    last_login_at: '2026-10-08T01:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    ...overrides,
  }
}

const USERS: ManagedUser[] = [
  user({}),
  user({
    id: 'u-alice',
    username: 'alice',
    display_name: 'Alice',
    role: 'viewer',
    locked: true,
    last_login_at: null,
  }),
  user({ id: 'u-dir', username: 'carol@example.com', role: 'operator', realm: 'dir:1', is_local: false }),
]

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

type Call = { url: string; method: string; body: unknown }

function stubApi(handler: (call: Call) => Response | undefined = () => undefined) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        url: String(input),
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      }
      calls.push(call)
      const custom = handler(call)
      if (custom) return Promise.resolve(custom)
      if (call.url === '/api/auth/users' && call.method === 'GET') return Promise.resolve(json(USERS))
      if (call.method === 'DELETE' || call.url.endsWith('/password') || call.url.endsWith('/revoke')) {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(json(USERS[1]))
    }),
  )
  return calls
}

function renderPanel(onError = vi.fn()) {
  render(
    <AuthContext.Provider value={{ me: ME, hasRole: (r) => roleAtLeast(ME.role, r), logout: async () => {} }}>
      <TimeZoneProvider>
        <UsersPanel onError={onError} />
      </TimeZoneProvider>
    </AuthContext.Provider>,
  )
  return onError
}

function row(name: string): HTMLElement {
  const cell = screen.getByText(name, { selector: '.users-panel__name, .users-panel__name *' })
  const tr = cell.closest('tr')
  if (!tr) throw new Error(`row for ${name} not found`)
  return tr
}

describe('UsersPanel', () => {
  beforeEach(() => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('一覧にロール・状態・認証先を出し、自分自身は削除できない', async () => {
    stubApi()
    renderPanel()
    await screen.findByText('alice')
    const alice = row('alice')
    expect(within(alice).getByText('閲覧者')).toBeInTheDocument()
    expect(within(alice).getByText('ロック中')).toBeInTheDocument()
    expect(within(alice).getByRole('button', { name: 'ロック解除' })).toBeInTheDocument()
    expect(within(alice).getByRole('button', { name: '削除' })).toBeInTheDocument()

    const self = row('admin')
    expect(within(self).getByText('（あなた）')).toBeInTheDocument()
    expect(within(self).queryByRole('button', { name: '削除' })).not.toBeInTheDocument()

    // ディレクトリのユーザーはパスワードを持たない
    const carol = row('carol@example.com')
    expect(within(carol).getByText('ディレクトリ')).toBeInTheDocument()
    expect(within(carol).queryByRole('button', { name: 'パスワード再設定' })).not.toBeInTheDocument()
  })

  it('ローカルユーザーを作成する（確認欄が一致するまで作成できない）', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('alice')
    fireEvent.change(screen.getByLabelText('ユーザー名'), { target: { value: ' bob ' } })
    fireEvent.change(screen.getByLabelText('ロール'), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText('初期パスワード'), { target: { value: 'a long password' } })
    fireEvent.change(screen.getByLabelText('初期パスワード（確認）'), { target: { value: 'different' } })
    expect(screen.getByText('パスワードが一致しません。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '作成' })).toBeDisabled()

    fireEvent.change(screen.getByLabelText('初期パスワード（確認）'), { target: { value: 'a long password' } })
    fireEvent.click(screen.getByRole('button', { name: '作成' }))
    expect(await screen.findByRole('status')).toHaveTextContent('ユーザー bob を作成しました。')
    expect(calls.find((c) => c.method === 'POST')).toEqual({
      url: '/api/auth/users',
      method: 'POST',
      body: {
        username: 'bob',
        display_name: null,
        email: null,
        role: 'operator',
        password: 'a long password',
      },
    })
    expect(screen.getByLabelText('ユーザー名')).toHaveValue('')
  })

  it('サーバの理由（422 の detail）を表示する', async () => {
    stubApi((call) =>
      call.method === 'POST' ? json({ detail: 'パスワードは 12 文字以上にしてください。' }, 422) : undefined,
    )
    const onError = renderPanel()
    await screen.findByText('alice')
    fireEvent.change(screen.getByLabelText('ユーザー名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('初期パスワード'), { target: { value: 'short' } })
    fireEvent.change(screen.getByLabelText('初期パスワード（確認）'), { target: { value: 'short' } })
    fireEvent.click(screen.getByRole('button', { name: '作成' }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('パスワードは 12 文字以上にしてください。'))
  })

  it('ロールの変更は確認してから、変わった項目だけを送る', async () => {
    const calls = stubApi()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByLabelText('alice のロール'), { target: { value: 'operator' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('alice を更新しました。')
    expect(confirmSpy).toHaveBeenCalledWith('alice のログインはすべて解除されます。よろしいですか？')
    expect(calls.find((c) => c.method === 'PATCH')).toEqual({
      url: '/api/auth/users/u-alice',
      method: 'PATCH',
      body: { display_name: 'Alice', email: null, role: 'operator' },
    })
  })

  it('確認で取り消したら更新しない', async () => {
    const calls = stubApi()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByLabelText('有効'))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('ディレクトリのユーザーのロールは編集できない', async () => {
    stubApi()
    renderPanel()
    await screen.findByText('carol@example.com')
    fireEvent.click(within(row('carol@example.com')).getByRole('button', { name: '編集' }))
    expect(screen.getByLabelText('carol@example.com のロール')).toBeDisabled()
  })

  it('パスワードを再設定する', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: 'パスワード再設定' }))
    fireEvent.change(screen.getByLabelText('alice の新しいパスワード'), { target: { value: 'another password' } })
    fireEvent.change(screen.getByLabelText('alice の新しいパスワード（確認）'), {
      target: { value: 'another password' },
    })
    fireEvent.click(screen.getByRole('button', { name: '再設定' }))
    expect(await screen.findByRole('status')).toHaveTextContent('alice のパスワードを再設定しました')
    expect(calls.find((c) => c.url.endsWith('/password'))).toEqual({
      url: '/api/auth/users/u-alice/password',
      method: 'POST',
      body: { password: 'another password' },
    })
  })

  it('ロック解除・ログイン解除・削除を呼び出す', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: 'ロック解除' }))
    await screen.findByText('alice のロックを解除しました。')
    fireEvent.click(within(row('alice')).getByRole('button', { name: 'ログイン解除' }))
    await screen.findByText('alice のログインを解除しました。')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '削除' }))
    await screen.findByText('alice を削除しました。')
    expect(calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.url}`)).toEqual([
      'POST /api/auth/users/u-alice/unlock',
      'POST /api/auth/users/u-alice/sessions/revoke',
      'DELETE /api/auth/users/u-alice',
    ])
  })
})
