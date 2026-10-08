/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiGet } from '../api'
import { AuthGate } from './AuthGate'
import { useAuth } from './useAuth'

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN_ME = {
  auth_enabled: true,
  username: 'alice',
  display_name: 'Alice',
  role: 'admin',
  realm: 'local',
  can_change_password: true,
}
const LOCAL_ONLY = { auth_enabled: true, realms: [{ id: 'local', name: 'ローカル', kind: 'local' }] }

function Probe() {
  const { me, hasRole, logout } = useAuth()
  return (
    <div>
      <p>ようこそ {me.username}</p>
      <p>{hasRole('admin') ? '管理者権限あり' : '管理者権限なし'}</p>
      <button type="button" onClick={() => void apiGet('/api/protected').catch(() => {})}>
        保護された API
      </button>
      <button type="button" onClick={() => void logout()}>
        出る
      </button>
    </div>
  )
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

function stubFetch(handler: Handler) {
  const fn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(handler(String(input), init)))
  vi.stubGlobal('fetch', fn)
  return fn
}

describe('AuthGate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('ログイン済みならアプリを表示する', async () => {
    stubFetch((url) => (url === '/api/auth/me' ? json(ADMIN_ME) : json({}, 404)))
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    expect(await screen.findByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.getByText('管理者権限あり')).toBeInTheDocument()
  })

  it('未ログインならログイン画面を出し、ログインに成功するとアプリを表示する', async () => {
    let loggedIn = false
    const fetchMock = stubFetch((url, init) => {
      if (url === '/api/auth/me') return loggedIn ? json(ADMIN_ME) : json({ detail: 'ログインが必要です。' }, 401)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/auth/login' && init?.method === 'POST') {
        loggedIn = true
        return json({ ...ADMIN_ME, role: 'viewer' })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    const user = await screen.findByLabelText('ユーザー名')
    // 認証先が 1 つだけなら選択欄を出さない
    expect(screen.queryByLabelText('認証先')).not.toBeInTheDocument()
    fireEvent.change(user, { target: { value: ' alice ' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'secret pass' } })
    fireEvent.click(screen.getByRole('button', { name: 'ログイン' }))

    expect(await screen.findByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.getByText('管理者権限なし')).toBeInTheDocument()
    const loginCall = fetchMock.mock.calls.find(([u]) => String(u) === '/api/auth/login')
    expect(loginCall).toBeDefined()
    const init = loginCall![1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ username: 'alice', password: 'secret pass', realm: 'local' })
    expect(new Headers(init.headers).get('X-Requested-With')).toBe('XMLHttpRequest')
  })

  it('ログインに失敗したらサーバの文言を出し、パスワード欄を空にする', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return json({ detail: 'ログインが必要です。' }, 401)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/auth/login') return json({ detail: 'ユーザー名またはパスワードが正しくありません。' }, 401)
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.change(await screen.findByLabelText('ユーザー名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'ログイン' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('ユーザー名またはパスワードが正しくありません。')
    expect(screen.getByLabelText('パスワード')).toHaveValue('')
  })

  it('ログインの試行が多すぎるときは待つよう案内する', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return json({}, 401)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/auth/login') return new Response('Too Many Requests', { status: 429 })
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.change(await screen.findByLabelText('ユーザー名'), { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'ログイン' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('しばらく待ってから')
  })

  it('認証先が 2 つ以上なら選ばせ、選んだ認証先でログインする', async () => {
    const fetchMock = stubFetch((url) => {
      if (url === '/api/auth/me') return json({}, 401)
      if (url === '/api/auth/realms') {
        return json({
          auth_enabled: true,
          realms: [
            { id: 'local', name: 'ローカル', kind: 'local' },
            { id: 'dir:1', name: '社内 AD', kind: 'ad' },
          ],
        })
      }
      if (url === '/api/auth/login') return json(ADMIN_ME)
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.change(await screen.findByLabelText('認証先'), { target: { value: 'dir:1' } })
    fireEvent.change(screen.getByLabelText('ユーザー名'), { target: { value: 'bob' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'ログイン' }))
    await screen.findByText('ようこそ alice')
    const init = fetchMock.mock.calls.find(([u]) => String(u) === '/api/auth/login')![1] as RequestInit
    expect(JSON.parse(String(init.body)).realm).toBe('dir:1')
  })

  it('API が 401 を返したらログイン画面に戻し、理由を表示する', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return json(ADMIN_ME)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/protected') return json({ detail: 'ログインが必要です。' }, 401)
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '保護された API' }))
    expect(await screen.findByRole('status')).toHaveTextContent('ログインの有効期限が切れました')
    expect(screen.queryByText('ようこそ alice')).not.toBeInTheDocument()
  })

  it('ログアウトするとログイン画面に戻る', async () => {
    const fetchMock = stubFetch((url) => {
      if (url === '/api/auth/me') return json(ADMIN_ME)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/auth/logout') return new Response(null, { status: 204 })
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '出る' }))
    expect(await screen.findByLabelText('ユーザー名')).toBeInTheDocument()
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u) === '/api/auth/logout' && (i as RequestInit).method === 'POST')).toBe(true),
    )
  })

  it('サーバに接続できないときは再試行できる', async () => {
    let fail = true
    stubFetch((url) => {
      if (url === '/api/auth/me') return fail ? new Response('down', { status: 503 }) : json(ADMIN_ME)
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    expect(await screen.findByRole('alert')).toHaveTextContent('リクエストに失敗しました')
    fail = false
    fireEvent.click(screen.getByRole('button', { name: '再試行' }))
    expect(await screen.findByText('ようこそ alice')).toBeInTheDocument()
  })
})
