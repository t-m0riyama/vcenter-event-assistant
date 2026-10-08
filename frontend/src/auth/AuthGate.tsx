import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  notifyUnauthorized,
  onPrincipalSeen,
  onUnauthorized,
  SESSION_EXPIRED_MESSAGE,
  setExpectedPrincipal,
} from '../api'
import type { Me, Realm, Role } from '../api/schemas'
import { fetchMe, fetchRealms, logout as logoutRequest } from './authApi'
import { AuthContext, type AuthContextValue } from './authContext'
import { LoginScreen } from './LoginScreen'
import { roleAtLeast } from './roles'
import { setActivityReporter } from '../userActivity'
import './auth.css'

/**
 * 利用者が同じ人か（別アカウントに切り替わったらアプリ本体を作り直す）。
 * 同じ名前で削除・再作成されたユーザーも別人として扱うため、利用者 ID を含める。
 */
function identityKey(me: Me): string {
  return `${me.realm}\u0000${me.username}\u0000${me.principal_id ?? ''}`
}

function sameMe(a: Me, b: Me): boolean {
  return (
    identityKey(a) === identityKey(b) &&
    a.principal_id === b.principal_id &&
    a.role === b.role &&
    a.display_name === b.display_name &&
    a.can_change_password === b.can_change_password &&
    a.session_activity_interval_seconds === b.session_activity_interval_seconds
  )
}

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
  const [state, setRawState] = useState<State>({ status: 'loading' })
  // 表示中の利用者（API 層が要求に付けてサーバが照合する）は、状態を切り替えるのと同時に更新する。
  // 利用者が替わるとアプリを作り直し、子の初回の取得は親の useEffect より先に走るため、effect での
  // 更新では前の利用者のまま送られて 409 で断られてしまう
  const setState = useCallback((next: State) => {
    setExpectedPrincipal(next.status === 'authenticated' ? (next.me.principal_id ?? null) : null)
    setRawState(next)
  }, [])
  const authenticatedRef = useRef(false)
  const checkingRef = useRef(false)
  // 認証状態が変わるたびに進む世代。非同期の確認結果が古い状態に対するものかを見分ける
  const generationRef = useRef(0)
  const meRef = useRef<Me | null>(null)
  useEffect(() => {
    authenticatedRef.current = state.status === 'authenticated'
    meRef.current = state.status === 'authenticated' ? state.me : null
    generationRef.current += 1
  }, [state])
  useEffect(() => () => setExpectedPrincipal(null), [])

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
    [beginOperation, setState],
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
  }, [beginOperation, setState, showLogin])

  useEffect(() => {
    void load()
  }, [load])

  /**
   * サーバが返した今のセッションの利用者を画面に反映する。別のタブで別のアカウントにログインし直すと
   * Cookie が替わり、このタブの要求も 401 にならずにその利用者として成功するため、``/api/auth/me`` の
   * 結果を受け取るたびに照合する。利用者が変われば下の key でアプリ本体を作り直し、前の利用者の
   * 画面の状態を残さない。
   */
  const applySession = useCallback(
    (current: Me) => {
      if (!authenticatedRef.current) return
      if (!meRef.current || !sameMe(meRef.current, current)) {
        beginOperation()
        setState({ status: 'authenticated', me: current })
      }
    },
    [beginOperation, setState],
  )

  /** 今のセッションを問い合わせて照合する。無効なら 401 と同じ流れ（確かめ直してログイン画面へ）にする。 */
  const checkSession = useCallback(async () => {
    const generation = generationRef.current
    const current = await fetchMe()
    if (generationRef.current !== generation || !authenticatedRef.current) return
    if (current) {
      applySession(current)
    } else {
      notifyUnauthorized()
    }
  }, [applySession])

  useEffect(
    () =>
      onUnauthorized((notice) => {
        if (!authenticatedRef.current || checkingRef.current) return
        // 401 が前のセッションで出した要求の遅れた応答かもしれない（ログインし直した後に届くことがある）。
        // 今のセッションが有効かを確かめ、無効なときだけログイン画面へ戻す。同時に何件 401 が来ても確認は 1 回
        checkingRef.current = true
        const generation = generationRef.current
        // null は未ログイン（401）の確認、undefined は確認できなかった（通信エラー・5xx など）
        const currentSession = async (): Promise<Me | null | undefined> => {
          try {
            return await fetchMe()
          } catch {
            return undefined
          }
        }
        void (async () => {
          let current: Me | null | undefined
          try {
            current = await currentSession()
            // 確認中に別のタブがログインして Cookie が替わった場合に備え、無効なら 1 回だけ確かめ直す
            if (current === null && generationRef.current === generation) {
              current = await currentSession()
            }
          } finally {
            checkingRef.current = false
          }
          // 確認中にこのタブでログイン・ログアウトなどが起きていたら、結果は古いので使わない
          if (generationRef.current !== generation || !authenticatedRef.current) return
          // 失効を確認できなかったときは画面を維持する（一時的な障害でログアウトさせない）
          if (current === undefined) return
          if (current) {
            // 別のタブで別のアカウントに切り替わっていたら、その利用者の表示に置き換える
            applySession(current)
            return
          }
          authenticatedRef.current = false
          await showLogin(notice ?? SESSION_EXPIRED_MESSAGE)
        })()
      }),
    [applySession, showLogin],
  )

  // ログイン中は、API を呼ばない操作もサーバの無操作期限が切れる前に伝える（間隔はサーバの更新間隔）
  const activityIntervalSeconds =
    state.status === 'authenticated' && state.me.auth_enabled
      ? (state.me.session_activity_interval_seconds ?? null)
      : undefined
  useEffect(() => {
    if (activityIntervalSeconds === undefined) return undefined
    return setActivityReporter(
      checkSession,
      activityIntervalSeconds ? activityIntervalSeconds * 1000 : undefined,
    )
  }, [activityIntervalSeconds, checkSession])

  // 別のタブでログインし直した後に戻ってきたときも、利用者を照合する
  const isAuthenticated = state.status === 'authenticated'

  // 応答が示す利用者とセッション（X-VEA-Principal）が表示中のものと違えば、すぐに照合する
  // （並べた別ウィンドウでログインし直すと、タブの切り替えも 401 も起きないため。同じアカウントでも
  // ロール変更後の再ログインならセッションが替わるので、ここで新しいロールに置き換わる）
  const reconcilingRef = useRef(false)
  const latestPrincipalRef = useRef<string | null>(null)
  const pendingMismatchRef = useRef(false)
  useEffect(() => {
    if (!isAuthenticated) return undefined
    const mismatched = () => {
      const known = meRef.current?.principal_id
      const latest = latestPrincipalRef.current
      return Boolean(authenticatedRef.current && known && latest && latest !== known)
    }
    return onPrincipalSeen((principalId) => {
      latestPrincipalRef.current = principalId
      if (!mismatched()) return
      if (reconcilingRef.current) {
        // 照合中に届いた食い違いは捨てずに、今の照合が終わってからもう一度照合する
        pendingMismatchRef.current = true
        return
      }
      reconcilingRef.current = true
      void (async () => {
        try {
          do {
            pendingMismatchRef.current = false
            try {
              await checkSession()
            } catch {
              // 確認できなくても画面はそのまま（照合中に新しい食い違いが届いていれば下でやり直す）
            }
          } while (pendingMismatchRef.current && mismatched())
        } finally {
          reconcilingRef.current = false
          pendingMismatchRef.current = false
        }
      })()
    })
  }, [checkSession, isAuthenticated])
  useEffect(() => {
    if (!isAuthenticated) return undefined
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return
      void checkSession().catch(() => {
        // 確認できなくても画面はそのまま（次の要求で分かる）
      })
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [checkSession, isAuthenticated])

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
        ? { me, hasRole: (role: Role) => roleAtLeast(me.role, role), logout, refresh: checkSession }
        : null,
    [checkSession, me, logout],
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
  return (
    <AuthContext.Provider value={value!}>
      <Fragment key={identityKey(state.me)}>{children}</Fragment>
    </AuthContext.Provider>
  )
}
