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

const refresh = vi.fn(async () => {})

function panel(onError: (e: string | null) => void, active = true, me: Me = ME) {
  return (
    <AuthContext.Provider value={{ me, hasRole: (r) => roleAtLeast(me.role, r), logout: async () => {}, refresh }}>
      <TimeZoneProvider>
        <UsersPanel onError={onError} active={active} />
      </TimeZoneProvider>
    </AuthContext.Provider>
  )
}

function renderPanel(onError = vi.fn()) {
  render(panel(onError))
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
      body: { role: 'operator' },
    })
  })

  it('表示名だけを変えたら表示名だけを送り、何も変えなければ送らない', async () => {
    const calls = stubApi()
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: '保存' })).not.toBeInTheDocument())
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)

    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByLabelText('alice の表示名'), { target: { value: ' Alice Liddell ' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('alice を更新しました。')
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      { display_name: 'Alice Liddell' },
    ])
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

  it('タブを開き直したときと「再読み込み」で一覧を読み直す', async () => {
    const calls = stubApi()
    const onError = vi.fn()
    const view = render(panel(onError))
    await screen.findByText('alice')
    const listLoads = () => calls.filter((c) => c.method === 'GET' && c.url === '/api/auth/users').length
    expect(listLoads()).toBe(1)
    view.rerender(panel(onError, false)) // ほかのタブへ移った（パネルは残る）
    view.rerender(panel(onError, true)) // 戻ってきた
    await waitFor(() => expect(listLoads()).toBe(2))
    fireEvent.click(screen.getByRole('button', { name: '再読み込み' }))
    await waitFor(() => expect(listLoads()).toBe(3))
  })

  it('編集中に一覧を読み直しても、編集を始めた時点から変えた項目だけを送る', async () => {
    let current = USERS
    const calls = stubApi((call) =>
      call.url === '/api/auth/users' && call.method === 'GET' ? json(current) : undefined,
    )
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    // 別の管理者が alice の表示名を変えた後に一覧を読み直した
    current = USERS.map((u) => (u.id === 'u-alice' ? { ...u, display_name: 'Alice (Ops)' } : u))
    fireEvent.click(screen.getByRole('button', { name: '再読み込み' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'GET')).toHaveLength(2))
    fireEvent.change(screen.getByLabelText('alice のロール'), { target: { value: 'operator' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('alice を更新しました。')
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ role: 'operator' }])
  })

  it('一覧の読み込みに成功したら、前の失敗表示を消す', async () => {
    let fail = true
    stubApi((call) =>
      call.url === '/api/auth/users' && call.method === 'GET' && fail ? new Response('down', { status: 503 }) : undefined,
    )
    const onError = vi.fn()
    const view = render(panel(onError))
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith(expect.stringContaining('リクエストに失敗しました')))
    fail = false
    view.rerender(panel(onError, false))
    view.rerender(panel(onError, true))
    await screen.findByText('alice')
    expect(onError).toHaveBeenLastCalledWith(null)
  })

  it('操作より前に始まった読み込みが後から届いても、操作後の一覧を上書きしない', async () => {
    let releaseStale: () => void = () => {}
    let gets = 0
    const calls = stubApi((call) => {
      if (call.url === '/api/auth/users' && call.method === 'GET') {
        gets += 1
        if (gets === 2) {
          // 2 回目（再読み込み）は遅れて、操作前の一覧を返す
          return undefined
        }
        if (gets >= 3) return json(USERS.filter((u) => u.id !== 'u-alice'))
      }
      if (call.method === 'DELETE') return new Response(null, { status: 204 })
      return undefined
    })
    // 2 回目の GET だけ保留する
    const originalFetch = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const pending = originalFetch(input, init)
        if (String(input) === '/api/auth/users' && (init?.method ?? 'GET') === 'GET' && gets === 2) {
          return new Promise<Response>((resolve) => {
            releaseStale = () => void pending.then(resolve)
          })
        }
        return pending
      }),
    )
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(screen.getByRole('button', { name: '再読み込み' })) // 遅れる読み込み
    await waitFor(() => expect(gets).toBe(2))
    fireEvent.click(within(row('alice')).getByRole('button', { name: '削除' }))
    await screen.findByText('alice を削除しました。')
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    releaseStale()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true)
  })

  it('操作の実行中は再読み込みなどを止め、操作のエラーを後の読み込みで消さない', async () => {
    let resolveDelete: (r: Response) => void = () => {}
    const calls = stubApi()
    const originalFetch = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'DELETE') {
          void originalFetch(input, init)
          return new Promise<Response>((resolve) => {
            resolveDelete = resolve
          })
        }
        return originalFetch(input, init)
      }),
    )
    const onError = vi.fn()
    const view = render(panel(onError))
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '削除' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '再読み込み' })).toBeDisabled())
    // タブを開き直しても、実行中は読み直さない
    const gets = () => calls.filter((c) => c.method === 'GET').length
    view.rerender(panel(onError, false))
    view.rerender(panel(onError, true))
    expect(gets()).toBe(1)
    resolveDelete(json({ detail: '最後の有効な admin は削除できません。' }, 409))
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith('最後の有効な admin は削除できません。'))
    expect(screen.getByRole('button', { name: '再読み込み' })).toBeEnabled()
    expect(gets()).toBe(1)
  })

  it('自分を編集したら、ログイン中の利用者を読み直す（ほかの利用者では読み直さない）', async () => {
    refresh.mockClear()
    stubApi()
    renderPanel()
    await screen.findByText('alice')
    fireEvent.click(within(row('alice')).getByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByLabelText('alice の表示名'), { target: { value: 'Alice L' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('alice を更新しました。')
    expect(refresh).not.toHaveBeenCalled()

    fireEvent.click(within(row('admin')).getByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByLabelText('admin の表示名'), { target: { value: 'Administrator' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByText('admin を更新しました。')
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
  })

  it('principal_id を返さない古いサーバでも、認証先とユーザー名で自分の行を見分ける', async () => {
    stubApi()
    render(panel(vi.fn(), true, { ...ME, principal_id: undefined }))
    await screen.findByText('alice')
    const self = row('admin')
    expect(within(self).getByText('（あなた）')).toBeInTheDocument()
    expect(within(self).queryByRole('button', { name: '削除' })).not.toBeInTheDocument()
  })
})
