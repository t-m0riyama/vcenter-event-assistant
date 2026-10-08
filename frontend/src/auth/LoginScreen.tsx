import { useState, type FormEvent } from 'react'
import type { Me, Realm } from '../api/schemas'
import { login } from './authApi'

type Props = {
  readonly realms: readonly Realm[]
  /** セッション切れなど、ログイン画面に戻った理由。 */
  readonly notice?: string | null
  readonly onLoggedIn: (me: Me) => void
}

/** ログイン画面。認証先（realm）は 2 件以上あるときだけ選ばせる。 */
export function LoginScreen({ realms, notice, onLoggedIn }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [realm, setRealm] = useState(realms[0]?.id ?? 'local')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      onLoggedIn(await login({ username: username.trim(), password, realm }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPassword('')
    } finally {
      setSubmitting(false)
    }
  }

  const noRealm = realms.length === 0

  return (
    <div className="login-screen">
      <form className="login-card panel" onSubmit={(e) => void submit(e)} aria-label="ログイン">
        <div className="login-card__brand">
          <img src="/favicon-small-light.svg" alt="" className="header__logo header__logo--light" width={44} height={44} />
          <img src="/favicon-small.svg" alt="" className="header__logo header__logo--dark" width={44} height={44} />
          <h1 className="login-card__title">vCenter Event Assistant</h1>
        </div>

        {notice && !error && (
          <p className="login-card__notice" role="status">
            {notice}
          </p>
        )}
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        {noRealm && (
          <div className="error-banner" role="alert">
            ログインできる認証先がありません。管理者に連絡してください。
          </div>
        )}

        {realms.length > 1 && (
          <label className="login-card__field">
            認証先
            <select value={realm} onChange={(e) => setRealm(e.target.value)} disabled={submitting}>
              {realms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="login-card__field">
          ユーザー名
          <input
            type="text"
            name="username"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={submitting || noRealm}
          />
        </label>
        <label className="login-card__field">
          パスワード
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting || noRealm}
          />
        </label>
        <button
          type="submit"
          className="btn btn--filled login-card__submit"
          disabled={submitting || noRealm || username.trim() === '' || password === ''}
          aria-busy={submitting ? 'true' : 'false'}
        >
          {submitting ? 'ログイン中…' : 'ログイン'}
        </button>
      </form>
    </div>
  )
}
