import { useEffect, useRef, type FormEvent, type ReactNode } from 'react'

export function DiagnosticSettingForm({ title, children, editing, busy, conflict, error, errorAction, canSave = true, onSubmit, onClose, onReload, onDelete }: {
  title: string
  children: ReactNode
  editing: boolean
  busy: boolean
  conflict: boolean
  error: string
  errorAction?: ReactNode
  canSave?: boolean
  onSubmit: () => void
  onClose: () => void
  onReload: () => void
  onDelete: () => void
}) {
  const form = useRef<HTMLFormElement>(null)
  useEffect(() => {
    form.current?.focus()
  }, [])

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (canSave && !busy && !conflict) onSubmit()
  }

  return <form ref={form} tabIndex={-1} aria-label={title} onSubmit={submit}>
    <fieldset disabled={busy || conflict}>
      <legend>{title}</legend>
      {children}
    </fieldset>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {error && errorAction}
    {conflict ? <>
      <p className="hint">最新の設定を確認してから、もう一度編集してください。</p>
      <button type="button" className="btn btn--gray" disabled={busy} onClick={onReload}>編集を破棄して読み直す</button>
    </> : <div className="diagnostics-actions">
      <button type="submit" className="btn btn--filled" disabled={busy || !canSave}>保存</button>
      <button type="button" className="btn btn--gray" disabled={busy} onClick={onClose}>キャンセル</button>
      {editing && <button type="button" className="btn btn--danger" disabled={busy} onClick={onDelete}>削除</button>}
    </div>}
  </form>
}
