import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { onUnauthorized, SESSION_EXPIRED_MESSAGE } from '../api'
import type { Me, Realm, Role } from '../api/schemas'
import { fetchMe, fetchRealms, logout as logoutRequest } from './authApi'
import { AuthContext, type AuthContextValue } from './authContext'
import { LoginScreen } from './LoginScreen'
import { roleAtLeast } from './roles'
import './auth.css'

type State =
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly message: string }
  | { readonly status: 'anonymous'; readonly realms: readonly Realm[]; readonly notice: string | null }
  | { readonly status: 'authenticated'; readonly me: Me }

/**
 * ログインしていなければログイン画面だけを出し、ログイン後に子要素（アプリ本体）を描画する。
 *
 * API が 401 を返したら（セッション切れ・失効）ログイン画面へ戻す。ログアウトやセッション切れで
 * 子要素はアンマウントされるので、前の利用者の画面の状態は残らない。
 */
export function AuthGate({ children }: { readonly children: ReactNode }) {
  const [state, setState] = useState<State>({ status: 'loading' })
  const authenticatedRef = useRef(false)
  useEffect(() => {
    authenticatedRef.current = state.status === 'authenticated'
  }, [state.status])

  const showLogin = useCallback(async (notice: string | null) => {
    try {
      const { realms } = await fetchRealms()
      setState({ status: 'anonymous', realms, notice })
    } catch (e) {
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [])

  const load = useCallback(async () => {
    setState({ status: 'loading' })
    try {
      const me = await fetchMe()
      if (me) {
        setState({ status: 'authenticated', me })
      } else {
        await showLogin(null)
      }
    } catch (e) {
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [showLogin])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () =>
      onUnauthorized(() => {
        // 同時に複数の API が 401 を返しても、ログイン画面へ戻すのは 1 回だけ
        if (!authenticatedRef.current) return
        authenticatedRef.current = false
        void showLogin(SESSION_EXPIRED_MESSAGE)
      }),
    [showLogin],
  )

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      await showLogin(null)
    }
  }, [showLogin])

  const me = state.status === 'authenticated' ? state.me : null
  const value = useMemo<AuthContextValue | null>(
    () =>
      me
        ? { me, hasRole: (role: Role) => roleAtLeast(me.role, role), logout }
        : null,
    [me, logout],
  )

  if (state.status === 'loading') {
    return <p className="hint auth-loading">読み込み中…</p>
  }
  if (state.status === 'error') {
    return (
      <div className="login-screen">
        <div className="login-card panel">
          <div className="error-banner" role="alert">
            {state.message}
          </div>
          <button type="button" className="btn btn--filled" onClick={() => void load()}>
            再試行
          </button>
        </div>
      </div>
    )
  }
  if (state.status === 'anonymous') {
    return (
      <LoginScreen
        realms={state.realms}
        notice={state.notice}
        onLoggedIn={(nextMe) => setState({ status: 'authenticated', me: nextMe })}
      />
    )
  }
  return <AuthContext.Provider value={value!}>{children}</AuthContext.Provider>
}
