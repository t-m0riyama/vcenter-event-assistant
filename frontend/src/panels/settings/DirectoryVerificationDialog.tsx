import { useEffect, useRef, useState, type FormEvent } from 'react'

/**
 * 保存の前に、新しい設定で管理者としてログインできることを確かめるための資格情報の入力（Issue #254）。
 *
 * サーバは、保存で管理者としてログインする手段を失うおそれがあるとき（操作している管理者がこのディレクトリの
 * ユーザーのとき、またはほかに管理者の経路がないとき）に 409 で資格情報を求める。入力した資格情報は確認に
 * 使うだけで保存されない。
 */
export function DirectoryVerificationDialog({
  directoryName,
  error,
  submitting,
  onSubmit,
  onClose,
}: {
  readonly directoryName: string
  /** 前回の確認が失敗した理由（サーバの文言）。 */
  readonly error: string | null
  readonly submitting: boolean
  readonly onSubmit: (credentials: { username: string; password: string }) => void
  readonly onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  useEffect(() => {
    const el = dialogRef.current
    if (el && !el.open) el.showModal()
  }, [])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (username.trim() === '' || password === '') return
    onSubmit({ username: username.trim(), password })
    // パスワードは画面に残さない（確認に失敗したら入れ直してもらう。成功すればダイアログは閉じる）
    setPassword('')
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog directory-verification-dialog"
      onClose={onClose}
      aria-labelledby="directory-verification-title"
    >
      <form onSubmit={submit}>
        <div className="dialog__header">
          <h2 id="directory-verification-title" className="dialog__title">
            管理者としてログインできるか確かめる
          </h2>
          <button
            type="button"
            className="btn dialog__close-btn"
            onClick={() => dialogRef.current?.close()}
            aria-label="閉じる"
          >
            ×
          </button>
        </div>
        <div className="dialog__body directory-verification-dialog__body">
          <p className="hint">
            この変更を保存すると、管理者としてログインする手段を失うおそれがあります。新しい設定で {directoryName}{' '}
            の管理者としてログインできるユーザーの資格情報を入力してください。確認にだけ使い、保存はしません。
          </p>
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          <label className="login-card__field">
            確認に使うユーザー名
            <input
              autoComplete="off"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={submitting}
            />
          </label>
          <label className="login-card__field">
            確認に使うパスワード
            <input
              type="password"
              autoComplete="off"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
          </label>
        </div>
        <div className="dialog__footer">
          <button type="button" className="btn btn--gray" onClick={() => dialogRef.current?.close()}>
            キャンセル
          </button>
          <button
            type="submit"
            className="btn btn--filled"
            disabled={submitting || username.trim() === '' || password === ''}
            aria-busy={submitting ? 'true' : 'false'}
          >
            {submitting ? '確かめています…' : '確かめて保存'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
