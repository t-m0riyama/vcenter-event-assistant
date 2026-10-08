/**
 * @vitest-environment happy-dom
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode, useEffect, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiGet } from '../api'
import { AuthGate } from './AuthGate'
import { useAuth } from './useAuth'

/**
 * 保留中の effect を流す。表示が出た時点では、visibilitychange のリスナーを登録する effect が
 * まだ走っていないことがある（その間に送ったイベントは取りこぼされ、CI でまれに落ちる）。
 */
async function flushEffects(): Promise<void> {
  await act(async () => {})
}

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
  const [logoutError, setLogoutError] = useState<string | null>(null)
  return (
    <div>
      {logoutError && <p>ログアウト失敗: {logoutError}</p>}
      <p>ようこそ {me.username}</p>
      <p>{hasRole('admin') ? '管理者権限あり' : '管理者権限なし'}</p>
      <button type="button" onClick={() => void apiGet('/api/protected').catch(() => {})}>
        保護された API
      </button>
      <button type="button" onClick={() => logout().catch((e: Error) => setLogoutError(e.message))}>
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

  it('StrictMode で二重に走った読み込みの遅い結果が、ログイン後の画面を戻さない', async () => {
    const pendingRealms: Array<(r: Response) => void> = []
    stubFetch((url) => {
      if (url === '/api/auth/me') return json({ detail: 'ログインが必要です。' }, 401)
      if (url === '/api/auth/realms') {
        // 1 回目はすぐ返し、2 回目以降は保留する
        if (pendingRealms.length === 0) {
          pendingRealms.push(() => {})
          return json(LOCAL_ONLY)
        }
        return new Promise<Response>((resolve) => pendingRealms.push(resolve))
      }
      if (url === '/api/auth/login') return json(ADMIN_ME)
      return json({}, 404)
    })
    render(
      <StrictMode>
        <AuthGate>
          <Probe />
        </AuthGate>
      </StrictMode>,
    )
    const user = await screen.findByLabelText('ユーザー名')
    fireEvent.change(user, { target: { value: 'alice' } })
    fireEvent.change(screen.getByLabelText('パスワード'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'ログイン' }))
    expect(await screen.findByText('ようこそ alice')).toBeInTheDocument()

    // 保留していた古い認証先の取得が、ログインの後で返ってくる
    pendingRealms.slice(1).forEach((resolve) => resolve(json(LOCAL_ONLY)))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
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

  it('API が 401 を返し、セッションも無効ならログイン画面に戻して理由を表示する', async () => {
    let sessionValid = true
    stubFetch((url) => {
      if (url === '/api/auth/me') return sessionValid ? json(ADMIN_ME) : json({ detail: 'ログインが必要です。' }, 401)
      if (url === '/api/protected') {
        sessionValid = false
        return json({ detail: 'ログインが必要です。' }, 401)
      }
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
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

  it('前のセッションの遅れた 401 では、有効な今のセッションを追い出さない', async () => {
    const fetchMock = stubFetch((url) => {
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
    // 再確認の /api/auth/me（2 回目）が終わるまで待つ
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/auth/me')).toHaveLength(2),
    )
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
  })

  it('再確認の途中で別のタブがログインし直したら、そのセッションを追い出さない', async () => {
    // 1 回目の再確認は古いセッションの Cookie で送られて 401、その間に別タブが新しいセッションを作った
    let meCalls = 0
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        meCalls += 1
        return meCalls === 2 ? json({ detail: 'ログインが必要です。' }, 401) : json(ADMIN_ME)
      }
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
    await waitFor(() => expect(meCalls).toBe(3))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
  })

  it('再確認で別のアカウントに切り替わっていたら、その利用者に置き換えてアプリを作り直す', async () => {
    let mounts = 0
    function MountCounter() {
      const [id] = useState(() => {
        mounts += 1
        return mounts
      })
      return <p>マウント {id}</p>
    }
    let switched = false
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json(switched ? { ...ADMIN_ME, username: 'bob', display_name: 'Bob', role: 'viewer' } : ADMIN_ME)
      }
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/protected') {
        // 別のタブで bob としてログインし直した後に、前のセッションの要求が 401 になった
        switched = true
        return json({ detail: 'ログインが必要です。' }, 401)
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
        <MountCounter />
      </AuthGate>,
    )
    expect(await screen.findByText('マウント 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    expect(await screen.findByText('ようこそ bob')).toBeInTheDocument()
    expect(screen.getByText('管理者権限なし')).toBeInTheDocument()
    // 前の利用者の画面の状態は残さない
    expect(screen.getByText('マウント 2')).toBeInTheDocument()
  })

  it('タブに戻ったときに別のアカウントに替わっていたら（401 なし）、その利用者に置き換える', async () => {
    let switched = false
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json(switched ? { ...ADMIN_ME, username: 'bob', role: 'viewer' } : ADMIN_ME)
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    await flushEffects()
    // 別のタブで bob としてログインし直した（Cookie が替わり、API は 401 にならない）
    switched = true
    document.dispatchEvent(new Event('visibilitychange'))
    expect(await screen.findByText('ようこそ bob')).toBeInTheDocument()
    expect(screen.getByText('管理者権限なし')).toBeInTheDocument()
  })

  it('タブに戻ったときにセッションが切れていたら、ログイン画面に戻す', async () => {
    let loggedOut = false
    stubFetch((url) => {
      if (url === '/api/auth/me') return loggedOut ? json({ detail: 'ログインが必要です。' }, 401) : json(ADMIN_ME)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    await flushEffects()
    loggedOut = true
    document.dispatchEvent(new Event('visibilitychange'))
    expect(await screen.findByRole('status')).toHaveTextContent('ログインの有効期限が切れました')
  })

  it('401 の後の再確認が一時的な障害で失敗しても、ログイン画面に戻さない', async () => {
    let failing = false
    stubFetch((url) => {
      if (url === '/api/auth/me') return failing ? new Response('down', { status: 503 }) : json(ADMIN_ME)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/protected') {
        failing = true
        return json({ detail: 'ログインが必要です。' }, 401)
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
  })

  it('応答の利用者 ID が表示中の利用者と違えば（401 もタブ切り替えもなし）、照合して置き換える', async () => {
    let switched = false
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json(
          switched
            ? { ...ADMIN_ME, username: 'bob', role: 'viewer', principal_id: 'id-bob' }
            : { ...ADMIN_ME, principal_id: 'id-alice' },
        )
      }
      if (url === '/api/protected') {
        // 並べた別ウィンドウで bob としてログインし直した後の、成功した応答
        switched = true
        return new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-bob' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    expect(await screen.findByText('ようこそ bob')).toBeInTheDocument()
    expect(screen.getByText('管理者権限なし')).toBeInTheDocument()
  })

  it('同じ名前で作り直された別のユーザーに替わったら、アプリを作り直す', async () => {
    let mounts = 0
    function MountCounter() {
      const [id] = useState(() => {
        mounts += 1
        return mounts
      })
      return <p>マウント {id}</p>
    }
    let recreated = false
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json({ ...ADMIN_ME, principal_id: recreated ? 'id-new' : 'id-old' })
      }
      if (url === '/api/protected') {
        recreated = true
        return new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-new' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
        <MountCounter />
      </AuthGate>,
    )
    expect(await screen.findByText('マウント 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    expect(await screen.findByText('マウント 2')).toBeInTheDocument()
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
  })

  it('同じ利用者が別のウィンドウでログインし直す（ロール変更後など）と、新しいロールに置き換える', async () => {
    let relogged = false
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json(
          relogged
            ? { ...ADMIN_ME, role: 'viewer', principal_id: 'id-alice:session-2' }
            : { ...ADMIN_ME, principal_id: 'id-alice:session-1' },
        )
      }
      if (url === '/api/protected') {
        relogged = true
        return new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-alice:session-2' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    expect(await screen.findByText('管理者権限あり')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    expect(await screen.findByText('管理者権限なし')).toBeInTheDocument()
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
  })

  it('利用者が切り替わって作り直した画面の最初の要求は、新しい利用者として送る', async () => {
    const initialHeaders: (string | null)[] = []
    function InitialLoader() {
      useEffect(() => {
        void apiGet('/api/initial').catch(() => {})
      }, [])
      return null
    }
    let switched = false
    stubFetch((url, init) => {
      if (url === '/api/auth/me') {
        return json({ ...ADMIN_ME, principal_id: switched ? 'id-bob:s1' : 'id-alice:s1' })
      }
      if (url === '/api/initial') {
        initialHeaders.push(new Headers(init?.headers).get('X-VEA-Expected-Principal'))
        return json({})
      }
      if (url === '/api/protected') {
        switched = true
        return new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-bob:s1' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
        <InitialLoader />
      </AuthGate>,
    )
    await waitFor(() => expect(initialHeaders).toEqual(['id-alice:s1']))
    fireEvent.click(screen.getByRole('button', { name: '保護された API' }))
    await waitFor(() => expect(initialHeaders).toEqual(['id-alice:s1', 'id-bob:s1']))
  })

  it('別のタブで別の利用者に切り替わっていたら、ログアウトせずにその利用者へ置き換える', async () => {
    let switched = false
    const fetchMock = stubFetch((url) => {
      if (url === '/api/auth/me') {
        return json(
          switched
            ? { ...ADMIN_ME, username: 'bob', principal_id: 'id-bob:s1' }
            : { ...ADMIN_ME, principal_id: 'id-alice:s1' },
        )
      }
      if (url === '/api/auth/logout') {
        switched = true
        return new Response('{"detail":"x"}', { status: 409, headers: { 'X-VEA-Principal': 'id-bob:s1' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    fireEvent.click(screen.getByRole('button', { name: '出る' }))
    expect(await screen.findByText('ようこそ bob')).toBeInTheDocument()
    const logoutCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/auth/logout')
    expect(new Headers(logoutCall?.[1]?.headers).get('X-VEA-Expected-Principal')).toBe('id-alice:s1')
  })

  it('照合中に届いた食い違いは、照合が一時的に失敗しても後でやり直す', async () => {
    let meCalls = 0
    let releaseFirstCheck: () => void = () => {}
    stubFetch((url) => {
      if (url === '/api/auth/me') {
        meCalls += 1
        if (meCalls === 1) return json({ ...ADMIN_ME, principal_id: 'id-alice' })
        if (meCalls === 2) {
          // 1 回目の照合は保留した後に一時的な障害で失敗する
          return new Promise<Response>((resolve) => {
            releaseFirstCheck = () => resolve(new Response('down', { status: 503 }))
          })
        }
        return json({ ...ADMIN_ME, username: 'bob', role: 'viewer', principal_id: 'id-bob' })
      }
      if (url === '/api/protected') {
        return new Response('{}', { status: 200, headers: { 'X-VEA-Principal': 'id-bob' } })
      }
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    await screen.findByText('ようこそ alice')
    fireEvent.click(screen.getByRole('button', { name: '保護された API' })) // 照合が始まる
    await waitFor(() => expect(meCalls).toBe(2))
    fireEvent.click(screen.getByRole('button', { name: '保護された API' })) // 照合中に届いた食い違い
    await new Promise((resolve) => setTimeout(resolve, 0))
    releaseFirstCheck()
    expect(await screen.findByText('ようこそ bob')).toBeInTheDocument()
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

  it('ログアウトに失敗したらログイン画面に戻さず、失敗を伝える', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return json(ADMIN_ME)
      if (url === '/api/auth/realms') return json(LOCAL_ONLY)
      if (url === '/api/auth/logout') return new Response('down', { status: 503 })
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '出る' }))
    expect(await screen.findByText(/ログアウト失敗/)).toBeInTheDocument()
    expect(screen.getByText('ようこそ alice')).toBeInTheDocument()
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
  })

  it('ログアウト後は認証先の取得を待たずにアプリを外す', async () => {
    let releaseRealms: (r: Response) => void = () => {}
    stubFetch((url) => {
      if (url === '/api/auth/me') return json(ADMIN_ME)
      if (url === '/api/auth/realms') return new Promise<Response>((resolve) => (releaseRealms = resolve))
      if (url === '/api/auth/logout') return new Response(null, { status: 204 })
      return json({}, 404)
    })
    render(
      <AuthGate>
        <Probe />
      </AuthGate>,
    )
    fireEvent.click(await screen.findByRole('button', { name: '出る' }))
    await waitFor(() => expect(screen.queryByText('ようこそ alice')).not.toBeInTheDocument())
    expect(screen.queryByLabelText('ユーザー名')).not.toBeInTheDocument()
    releaseRealms(json(LOCAL_ONLY))
    expect(await screen.findByLabelText('ユーザー名')).toBeInTheDocument()
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
