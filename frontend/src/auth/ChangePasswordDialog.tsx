import { useEffect, useRef, useState, type FormEvent } from 'react'
import { changeOwnPassword } from './authApi'

/** 自分のパスワードを変更するダイアログ（ローカルユーザーのみ）。 */
export function ChangePasswordDialog({ onClose }: { readonly onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const el = dialogRef.current
    if (el && !el.open) el.showModal()
  }, [])

  const close = () => dialogRef.current?.close()

  const mismatch = confirm !== '' && next !== confirm

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (next !== confirm) return
    setSubmitting(true)
    setError(null)
    try {
      await changeOwnPassword({ current_password: current, new_password: next })
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <dialog ref={dialogRef} className="dialog change-password-dialog" onClose={onClose} aria-labelledby="change-password-title">
      <form onSubmit={(e) => void submit(e)}>
        <div className="dialog__header">
          <h2 id="change-password-title" className="dialog__title">
            パスワードの変更
          </h2>
          <button type="button" className="btn dialog__close-btn" onClick={close} aria-label="閉じる">
            ×
          </button>
        </div>
        <div className="dialog__body change-password-dialog__body">
          {done && (
            <p className="change-password-dialog__done" role="status">
              パスワードを変更しました。ほかの端末のログインは解除されました。
            </p>
          )}
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          <label className="login-card__field">
            現在のパスワード
            <input
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              disabled={submitting}
            />
          </label>
          <label className="login-card__field">
            新しいパスワード
            <input
              type="password"
              autoComplete="new-password"
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
              disabled={submitting}
            />
          </label>
          <label className="login-card__field">
            新しいパスワード（確認）
            <input
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={submitting}
              aria-invalid={mismatch ? 'true' : 'false'}
            />
          </label>
          {mismatch && <p className="field-error">新しいパスワードが一致しません。</p>}
        </div>
        <div className="dialog__footer">
          <button type="button" className="btn btn--gray" onClick={close}>
            閉じる
          </button>
          <button
            type="submit"
            className="btn btn--filled"
            disabled={submitting || current === '' || next === '' || next !== confirm}
          >
            変更する
          </button>
        </div>
      </form>
    </dialog>
  )
}
