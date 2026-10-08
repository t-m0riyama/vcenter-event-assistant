import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { managedUserListSchema, type ManagedUser, type Role } from '../../api/schemas'
import { ROLE_LABELS } from '../../auth/roles'
import { useAuth } from '../../auth/useAuth'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import './UsersPanel.css'

const ROLES: readonly Role[] = ['viewer', 'operator', 'admin']

type CreateForm = {
  username: string
  display_name: string
  email: string
  role: Role
  password: string
  confirm: string
}

const EMPTY_CREATE: CreateForm = {
  username: '',
  display_name: '',
  email: '',
  role: 'viewer',
  password: '',
  confirm: '',
}

type EditForm = {
  display_name: string
  email: string
  role: Role
  is_active: boolean
}

type PasswordForm = { password: string; confirm: string }

function optionalText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** ``principal_id``（利用者 ID:セッション ID）から利用者 ID を取り出す。 */
function principalUserId(principalId: string | null | undefined): string | null {
  return principalId ? principalId.split(':')[0] : null
}

/** ユーザー管理パネル（admin のみ）。ローカルユーザーの作成と、全ユーザーのロール・有効状態の管理。 */
export function UsersPanel({
  onError,
  active = true,
}: {
  onError: (e: string | null) => void
  /** サブタブが表示中か。開き直すたびに一覧を読み直す（ほかの管理者の変更やログインを反映するため）。 */
  active?: boolean
}) {
  const { me } = useAuth()
  const { timeZone } = useTimeZone()
  const selfId = principalUserId(me.principal_id)
  const [list, setList] = useState<ManagedUser[]>([])
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<EditForm>({
    display_name: '',
    email: '',
    role: 'viewer',
    is_active: true,
  })
  // 編集を始めた時点の値。一覧を読み直しても変えず、これと比べて変えた項目だけを送る
  const [editOriginal, setEditOriginal] = useState<EditForm | null>(null)
  const [passwordFor, setPasswordFor] = useState<string | null>(null)
  const [passwordForm, setPasswordForm] = useState<PasswordForm>({ password: '', confirm: '' })
  const [notice, setNotice] = useState<string | null>(null)

  // 一覧の読み込みと操作の通し番号。後から届いた古い読み込みの結果で、操作後の一覧や
  // 新しいエラー表示を上書きしないため、最新のものだけを反映する
  const sequenceRef = useRef(0)

  const load = useCallback(async () => {
    const sequence = ++sequenceRef.current
    try {
      const data = await apiGet<unknown>('/api/auth/users')
      if (sequence !== sequenceRef.current) return
      setList(managedUserListSchema.parse(data))
      // 前の読み込みの失敗表示を消す（タブを開き直しての再試行が成功した場合も）
      onError(null)
    } catch (e) {
      if (sequence !== sequenceRef.current) return
      onError(toErrorMessage(e))
    }
  }, [onError])

  useEffect(() => {
    if (!active) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch whenever the tab is shown
    void load()
  }, [active, load])

  /** 操作を実行し、成功したら一覧を読み直してお知らせを出す。 */
  const run = async (action: () => Promise<unknown>, done: string): Promise<boolean> => {
    // 実行中の読み込みの結果は捨てる（操作前の一覧で上書きしたり、操作のエラーを消したりしないため）
    sequenceRef.current += 1
    onError(null)
    setNotice(null)
    try {
      await action()
      setNotice(done)
      await load()
      return true
    } catch (e) {
      onError(toErrorMessage(e))
      return false
    }
  }

  const createMismatch = form.confirm !== '' && form.password !== form.confirm
  const canCreate = form.username.trim() !== '' && form.password !== '' && form.password === form.confirm

  const create = async () => {
    if (!canCreate) return
    const ok = await run(
      () =>
        apiPost('/api/auth/users', {
          username: form.username.trim(),
          display_name: optionalText(form.display_name),
          email: optionalText(form.email),
          role: form.role,
          password: form.password,
        }),
      `ユーザー ${form.username.trim()} を作成しました。`,
    )
    if (ok) setForm(EMPTY_CREATE)
  }

  const startEdit = (u: ManagedUser) => {
    setPasswordFor(null)
    const original: EditForm = {
      display_name: u.display_name ?? '',
      email: u.email ?? '',
      role: u.role,
      is_active: u.is_active,
    }
    setEditingId(u.id)
    setEditOriginal(original)
    setEditForm(original)
  }

  const saveEdit = async (u: ManagedUser) => {
    if (!editOriginal) return
    // 編集を始めた時点から変えた項目だけを送る（別の管理者が同時に変えたほかの項目を、
    // 編集開始時の値で上書きしないため。途中で一覧を読み直しても基準は変えない）
    const body: Record<string, unknown> = {}
    const displayName = optionalText(editForm.display_name)
    const email = optionalText(editForm.email)
    if (displayName !== optionalText(editOriginal.display_name)) body.display_name = displayName
    if (email !== optionalText(editOriginal.email)) body.email = email
    const roleChanged = editForm.role !== editOriginal.role
    const activeChanged = editForm.is_active !== editOriginal.is_active
    if (roleChanged) body.role = editForm.role
    if (activeChanged) body.is_active = editForm.is_active
    if (Object.keys(body).length === 0) {
      setEditingId(null)
      return
    }
    if (roleChanged || activeChanged) {
      const target = u.id === selfId ? 'あなた自身' : u.username
      if (!confirm(`${target} のログインはすべて解除されます。よろしいですか？`)) return
    }
    const ok = await run(() => apiPatch(`/api/auth/users/${u.id}`, body), `${u.username} を更新しました。`)
    if (ok) setEditingId(null)
  }

  const startPasswordReset = (u: ManagedUser) => {
    setEditingId(null)
    setPasswordFor(u.id)
    setPasswordForm({ password: '', confirm: '' })
  }

  const resetMismatch = passwordForm.confirm !== '' && passwordForm.password !== passwordForm.confirm
  const canReset = passwordForm.password !== '' && passwordForm.password === passwordForm.confirm

  const resetPassword = async (u: ManagedUser) => {
    if (!canReset) return
    const ok = await run(
      () => apiPost(`/api/auth/users/${u.id}/password`, { password: passwordForm.password }),
      `${u.username} のパスワードを再設定しました（ロックも解除し、ほかのログインは解除しました）。`,
    )
    if (ok) setPasswordFor(null)
  }

  const unlock = (u: ManagedUser) =>
    void run(() => apiPost(`/api/auth/users/${u.id}/unlock`, {}), `${u.username} のロックを解除しました。`)

  const revokeSessions = (u: ManagedUser) => {
    const message =
      u.id === selfId
        ? 'この画面以外のあなたのログインをすべて解除します。よろしいですか？'
        : `${u.username} のログインをすべて解除します。よろしいですか？`
    if (!confirm(message)) return
    void run(() => apiPost(`/api/auth/users/${u.id}/sessions/revoke`, {}), `${u.username} のログインを解除しました。`)
  }

  const remove = (u: ManagedUser) => {
    if (!confirm(`${u.username} を削除しますか？ この操作は元に戻せません。`)) return
    void run(() => apiDelete(`/api/auth/users/${u.id}`), `${u.username} を削除しました。`)
  }

  return (
    <div className="panel users-panel">
      <p className="hint">
        ログインできるユーザーを管理します。ロールの変更・無効化・パスワード再設定をすると、そのユーザーのログインは解除されます。最後の有効な管理者は降格・無効化・削除できません。
      </p>
      {notice && (
        <p className="users-panel__notice" role="status">
          {notice}
        </p>
      )}

      <h2>ローカルユーザーの作成</h2>
      <form
        className="form-grid users-panel__form"
        onSubmit={(e) => {
          e.preventDefault()
          void create()
        }}
      >
        <label>
          ユーザー名
          <input
            value={form.username}
            autoComplete="off"
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
        </label>
        <label>
          表示名（任意）
          <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </label>
        <label>
          メールアドレス（任意）
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </label>
        <label>
          ロール
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </label>
        <label>
          初期パスワード
          <input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </label>
        <label>
          初期パスワード（確認）
          <input
            type="password"
            autoComplete="new-password"
            value={form.confirm}
            aria-invalid={createMismatch}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
          />
        </label>
        {createMismatch && <p className="users-panel__field-error">パスワードが一致しません。</p>}
        <div>
          <button type="submit" className="btn btn--filled" disabled={!canCreate}>
            作成
          </button>
        </div>
      </form>

      <div className="users-panel__list-header">
        <h2>一覧</h2>
        <button
          type="button"
          className="btn btn--gray"
          onClick={() => {
            onError(null)
            void load()
          }}
        >
          再読み込み
        </button>
      </div>
      <table className="table users-panel__table">
        <thead>
          <tr>
            <th>ユーザー</th>
            <th>認証先</th>
            <th>ロール</th>
            <th>状態</th>
            <th>最終ログイン</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((u) => {
            const isSelf = u.id === selfId
            return (
              <Fragment key={u.id}>
                {editingId === u.id ? (
                  <tr>
                    <td>
                      <div className="users-panel__name">{u.username}</div>
                      <input
                        aria-label={`${u.username} の表示名`}
                        placeholder="表示名"
                        value={editForm.display_name}
                        onChange={(e) => setEditForm({ ...editForm, display_name: e.target.value })}
                      />
                      <input
                        type="email"
                        aria-label={`${u.username} のメールアドレス`}
                        placeholder="メールアドレス"
                        value={editForm.email}
                        onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                      />
                    </td>
                    <td>{u.is_local ? 'ローカル' : 'ディレクトリ'}</td>
                    <td>
                      <select
                        aria-label={`${u.username} のロール`}
                        value={editForm.role}
                        disabled={!u.is_local}
                        title={u.is_local ? undefined : 'ディレクトリのユーザーのロールはグループの対応表で決まります'}
                        onChange={(e) => setEditForm({ ...editForm, role: e.target.value as Role })}
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={editForm.is_active}
                          onChange={(e) => setEditForm({ ...editForm, is_active: e.target.checked })}
                        />
                        有効
                      </label>
                    </td>
                    <td>{u.last_login_at ? formatIsoInTimeZone(u.last_login_at, timeZone) : '—'}</td>
                    <td className="actions">
                      <button type="button" className="btn btn--filled" onClick={() => void saveEdit(u)}>
                        保存
                      </button>
                      <button type="button" className="btn btn--gray" onClick={() => setEditingId(null)}>
                        キャンセル
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr>
                    <td>
                      <div className="users-panel__name">
                        {u.username}
                        {isSelf && <span className="users-panel__self">（あなた）</span>}
                      </div>
                      {u.display_name && <div className="users-panel__sub">{u.display_name}</div>}
                      {u.email && <div className="users-panel__sub">{u.email}</div>}
                    </td>
                    <td>{u.is_local ? 'ローカル' : 'ディレクトリ'}</td>
                    <td>{ROLE_LABELS[u.role]}</td>
                    <td>
                      <span className="users-panel__badges">
                        {u.is_active ? (
                          <span className="badge badge--info">有効</span>
                        ) : (
                          <span className="badge">無効</span>
                        )}
                        {u.locked && <span className="badge badge--warning">ロック中</span>}
                      </span>
                    </td>
                    <td>{u.last_login_at ? formatIsoInTimeZone(u.last_login_at, timeZone) : '—'}</td>
                    <td className="actions">
                      <button type="button" className="btn btn--gray" onClick={() => startEdit(u)}>
                        編集
                      </button>
                      {u.is_local && (
                        <button type="button" className="btn btn--gray" onClick={() => startPasswordReset(u)}>
                          パスワード再設定
                        </button>
                      )}
                      {u.locked && (
                        <button type="button" className="btn btn--gray" onClick={() => unlock(u)}>
                          ロック解除
                        </button>
                      )}
                      <button type="button" className="btn btn--gray" onClick={() => revokeSessions(u)}>
                        ログイン解除
                      </button>
                      {!isSelf && (
                        <button type="button" className="btn btn--danger" onClick={() => remove(u)}>
                          削除
                        </button>
                      )}
                    </td>
                  </tr>
                )}
                {passwordFor === u.id && (
                  <tr className="users-panel__password-row">
                    <td colSpan={6}>
                      <form
                        className="users-panel__password-form"
                        onSubmit={(e) => {
                          e.preventDefault()
                          void resetPassword(u)
                        }}
                      >
                        <label>
                          {u.username} の新しいパスワード
                          <input
                            type="password"
                            autoComplete="new-password"
                            value={passwordForm.password}
                            onChange={(e) => setPasswordForm({ ...passwordForm, password: e.target.value })}
                          />
                        </label>
                        <label>
                          {u.username} の新しいパスワード（確認）
                          <input
                            type="password"
                            autoComplete="new-password"
                            value={passwordForm.confirm}
                            aria-invalid={resetMismatch}
                            onChange={(e) => setPasswordForm({ ...passwordForm, confirm: e.target.value })}
                          />
                        </label>
                        {resetMismatch && <p className="users-panel__field-error">パスワードが一致しません。</p>}
                        <div className="actions">
                          <button type="submit" className="btn btn--filled" disabled={!canReset}>
                            再設定
                          </button>
                          <button type="button" className="btn btn--gray" onClick={() => setPasswordFor(null)}>
                            キャンセル
                          </button>
                        </div>
                      </form>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
