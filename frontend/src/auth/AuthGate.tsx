import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { onUnauthorized, SESSION_EXPIRED_MESSAGE } from '../api'
import type { Me, Realm, Role } from '../api/schemas'
import { fetchMe, fetchRealms, logout as logoutRequest } from './authApi'
import { AuthContext, type AuthContextValue } from './authContext'
import { LoginScreen } from './LoginScreen'
import { roleAtLeast } from './roles'
import { setActivityReporter } from '../userActivity'
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
  const checkingRef = useRef(false)
  // 認証状態が変わるたびに進む世代。非同期の確認結果が古い状態に対するものかを見分ける
  const generationRef = useRef(0)
  useEffect(() => {
    authenticatedRef.current = state.status === 'authenticated'
    generationRef.current += 1
  }, [state])

  // 状態を変える非同期処理（読み込み・ログイン画面の準備）の通し番号。結果を反映する時点で最新でなければ捨てる。
  // StrictMode の二重実行や、取得中にログインが済んだ場合に、古い結果で画面を戻さないため
  const operationRef = useRef(0)
  const beginOperation = useCallback(() => {
    operationRef.current += 1
    return operationRef.current
  }, [])

  const showLogin = useCallback(
    async (notice: string | null) => {
      const op = beginOperation()
      // 認証先の取得を待つ間もアプリ本体（前の利用者のデータ）を表示し続けないよう、先に外す
      setState({ status: 'loading' })
      try {
        const { realms } = await fetchRealms()
        if (op !== operationRef.current) return
        setState({ status: 'anonymous', realms, notice })
      } catch (e) {
        if (op !== operationRef.current) return
        setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
      }
    },
    [beginOperation],
  )

  // 初期状態が loading なので、ここでは同期的に state を変えない（再試行時は呼び出し側で loading にする）
  const load = useCallback(async () => {
    const op = beginOperation()
    try {
      const me = await fetchMe()
      if (op !== operationRef.current) return
      if (me) {
        setState({ status: 'authenticated', me })
      } else {
        await showLogin(null)
      }
    } catch (e) {
      if (op !== operationRef.current) return
      setState({ status: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }, [beginOperation, showLogin])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(
    () =>
      onUnauthorized(() => {
        if (!authenticatedRef.current || checkingRef.current) return
        // 401 が前のセッションで出した要求の遅れた応答かもしれない（ログインし直した後に届くことがある）。
        // 今のセッションが有効かを確かめ、無効なときだけログイン画面へ戻す。同時に何件 401 が来ても確認は 1 回
        checkingRef.current = true
        const generation = generationRef.current
        const sessionIsValid = async () => {
          try {
            return (await fetchMe()) !== null
          } catch {
            return false
          }
        }
        void (async () => {
          let stillValid: boolean
          try {
            stillValid = await sessionIsValid()
            // 確認中に別のタブがログインして Cookie が替わった場合に備え、無効なら 1 回だけ確かめ直す
            if (!stillValid && generationRef.current === generation) {
              stillValid = await sessionIsValid()
            }
          } finally {
            checkingRef.current = false
          }
          // 確認中にこのタブでログイン・ログアウトなどが起きていたら、結果は古いので使わない
          if (stillValid || generationRef.current !== generation || !authenticatedRef.current) return
          authenticatedRef.current = false
          await showLogin(SESSION_EXPIRED_MESSAGE)
        })()
      }),
    [showLogin],
  )

  // ログイン中は、API を呼ばない操作もサーバの無操作期限が切れる前に伝える
  const isAuthenticated = state.status === 'authenticated'
  useEffect(() => {
    if (!isAuthenticated) return undefined
    return setActivityReporter(() => fetchMe())
  }, [isAuthenticated])

  const logout = useCallback(async () => {
    // 失効を確認できたときだけログイン画面へ戻す。失敗したら例外を呼び出し元に返し、
    // ログアウトできたように見せない（共用端末で再読み込みすると入れてしまうため）
    await logoutRequest()
    authenticatedRef.current = false
    await showLogin(null)
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
          <button
            type="button"
            className="btn btn--filled"
            onClick={() => {
              setState({ status: 'loading' })
              void load()
            }}
          >
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
        onLoggedIn={(nextMe) => {
          // 取得中の古い処理（認証先の再取得など）が後からログイン画面へ戻さないよう、番号を進める
          beginOperation()
          setState({ status: 'authenticated', me: nextMe })
        }}
      />
    )
  }
  return <AuthContext.Provider value={value!}>{children}</AuthContext.Provider>
}
