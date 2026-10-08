import { useCallback, useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import {
  directoryListSchema,
  directoryPolicySchema,
  directoryTestResponseSchema,
  type Directory,
  type DirectoryPolicy,
  type DirectoryTestResponse,
} from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'
import { DirectoryForm } from './DirectoryForm'
import { DirectoryTestResult } from './DirectoryTestResult'
import {
  changesFromForm,
  connectionWarnings,
  createBody,
  emptyDirectoryForm,
  formFromDirectory,
  mappingsChanged,
  mappingsFromForm,
  type DirectoryFormState,
} from './directoryFormState'
import './DirectoriesPanel.css'

const KIND_LABELS: Record<Directory['kind'], string> = { ad: 'Active Directory', ldap: 'LDAP' }

/** 編集中の対象。新規作成か、保存済みのディレクトリか。 */
type Editing = { readonly mode: 'create' } | { readonly mode: 'edit'; readonly original: Directory }

/**
 * 認証ディレクトリ（AD / LDAP）の管理パネル（admin のみ）。
 *
 * 設定と対応表は 1 回の ``PATCH`` でまとめて保存する（分けて送ると、1 回目でログイン中のセッションが
 * 失効し、唯一の管理者が 2 回目を送れなくなるため）。接続試験は保存せずに編集中の値で行う。
 */
export function DirectoriesPanel({
  onError,
  active = true,
}: {
  onError: (e: string | null) => void
  /** サブタブが表示中か。開き直すたびに一覧を読み直す。 */
  active?: boolean
}) {
  const [list, setList] = useState<Directory[]>([])
  const [policy, setPolicy] = useState<DirectoryPolicy | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [form, setForm] = useState<DirectoryFormState>(emptyDirectoryForm)
  const [testUser, setTestUser] = useState({ username: '', password: '' })
  const [testResult, setTestResult] = useState<DirectoryTestResponse | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  // 一覧の読み込みと操作の通し番号（UsersPanel と同じ。古い読み込みの結果で上書きしない）
  const sequenceRef = useRef(0)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)

  const load = useCallback(async () => {
    const sequence = ++sequenceRef.current
    try {
      const [data, policyData] = await Promise.all([
        apiGet<unknown>('/api/auth/directories'),
        apiGet<unknown>('/api/auth/directories/policy'),
      ])
      if (sequence !== sequenceRef.current) return
      setList(directoryListSchema.parse(data))
      setPolicy(directoryPolicySchema.parse(policyData))
      onError(null)
    } catch (e) {
      if (sequence !== sequenceRef.current) return
      onError(toErrorMessage(e))
    }
  }, [onError])

  useEffect(() => {
    if (!active || busyRef.current) return
    void load()
  }, [active, load])

  /** 操作を実行する。成功したら ``done`` を出して一覧を読み直す（``done`` が null なら読み直さない）。 */
  const run = async <T,>(action: () => Promise<T>, done: string | null): Promise<T | undefined> => {
    sequenceRef.current += 1
    busyRef.current = true
    setBusy(true)
    onError(null)
    setNotice(null)
    try {
      const result = await action()
      if (done !== null) {
        setNotice(done)
        await load()
      }
      return result
    } catch (e) {
      onError(toErrorMessage(e))
      return undefined
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  const open = (next: Editing) => {
    setEditing(next)
    setForm(next.mode === 'edit' ? formFromDirectory(next.original) : emptyDirectoryForm())
    setTestUser({ username: '', password: '' })
    setTestResult(null)
    setNotice(null)
  }

  const close = () => {
    setEditing(null)
    setTestResult(null)
  }

  const testCredentials = () => ({
    username: testUser.username.trim() === '' ? null : testUser.username.trim(),
    password: testUser.password === '' ? null : testUser.password,
  })

  /** 編集中の値で接続試験をする（保存しない）。 */
  const runTest = async () => {
    if (!editing) return
    setTestResult(null)
    const result = await run(async () => {
      const data =
        editing.mode === 'create'
          ? await apiPost<unknown>('/api/auth/directories/test', { ...createBody(form), ...testCredentials() })
          : await apiPost<unknown>(`/api/auth/directories/${editing.original.id}/test`, {
              ...testCredentials(),
              changes: changesFromForm(editing.original, form),
              mappings: mappingsChanged(editing.original, form) ? mappingsFromForm(form) : null,
            })
      return directoryTestResponseSchema.parse(data)
    }, null)
    if (result) setTestResult(result)
  }

  const save = async () => {
    if (!editing) return
    if (editing.mode === 'create') {
      const ok = await run(() => apiPost('/api/auth/directories', createBody(form)), `${form.name.trim()} を追加しました。`)
      if (ok !== undefined) close()
      return
    }
    const { original } = editing
    // 設定と対応表を 1 回で送る（変えていなければ送らない）
    const body: Record<string, unknown> = changesFromForm(original, form)
    if (mappingsChanged(original, form)) body.mappings = mappingsFromForm(form)
    if (Object.keys(body).length === 0) {
      close()
      return
    }
    const ok = await run(
      () => apiPatch(`/api/auth/directories/${original.id}`, body),
      `${form.name.trim() || original.name} を保存しました。`,
    )
    if (ok !== undefined) close()
  }

  const remove = (d: Directory) => {
    const users = d.user_count > 0 ? `配下のユーザー ${d.user_count} 人と、` : ''
    if (!confirm(`${d.name} を削除しますか？ ${users}グループの対応表も削除されます。この操作は元に戻せません。`)) return
    void run(async () => {
      await apiDelete(`/api/auth/directories/${d.id}`)
      if (editing?.mode === 'edit' && editing.original.id === d.id) close()
      return true
    }, `${d.name} を削除しました。`)
  }

  const canSave = form.name.trim() !== '' && form.server_uris.trim() !== '' && form.user_search_base.trim() !== ''

  return (
    <div className="panel directories-panel">
      <fieldset className="directories-panel__fieldset" disabled={busy} aria-busy={busy}>
        <p className="hint">
          ログインに使う Active Directory / LDAP を管理します。ユーザーのロールは、グループとロールの対応表でログインのたびに決まります。
          接続先・検索・グループの設定や対応表を変えたり、ディレクトリを無効にしたりすると、そのディレクトリでログイン中のユーザーはログアウトされます。
        </p>
        {notice && (
          <p className="directories-panel__notice" role="status">
            {notice}
          </p>
        )}

        <div className="directories-panel__list-header">
          <h2>一覧</h2>
          <div className="actions">
            <button type="button" className="btn btn--filled" onClick={() => open({ mode: 'create' })}>
              ディレクトリを追加
            </button>
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
        </div>
        {list.length === 0 ? (
          <p className="hint">ディレクトリはありません。ローカルユーザーだけがログインできます。</p>
        ) : (
          <table className="table directories-panel__table">
            <thead>
              <tr>
                <th>名前</th>
                <th>種類</th>
                <th>状態</th>
                <th>ユーザー数</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id}>
                  <td>
                    <div className="directories-panel__name">{d.name}</div>
                    <div className="directories-panel__sub">{d.server_uris.join(', ')}</div>
                    {connectionWarnings(d).map((w) => (
                      <span key={w} className="badge badge--warning">
                        {w}
                      </span>
                    ))}
                  </td>
                  <td>{KIND_LABELS[d.kind]}</td>
                  <td>
                    {d.is_enabled ? <span className="badge badge--info">有効</span> : <span className="badge">無効</span>}
                  </td>
                  <td>{d.user_count}</td>
                  <td className="actions">
                    <button type="button" className="btn btn--gray" onClick={() => open({ mode: 'edit', original: d })}>
                      編集
                    </button>
                    <button
                      type="button"
                      className="btn btn--danger"
                      disabled={d.is_enabled}
                      title={d.is_enabled ? '有効なディレクトリは削除できません。先に無効にしてください。' : undefined}
                      onClick={() => remove(d)}
                    >
                      削除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {editing && (
          <section className="directories-panel__editor" aria-label="ディレクトリの設定">
            <h2>{editing.mode === 'create' ? 'ディレクトリの追加' : `${editing.original.name} の編集`}</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void save()
              }}
            >
              <DirectoryForm
                value={form}
                onChange={setForm}
                original={editing.mode === 'edit' ? editing.original : undefined}
                policy={policy}
              />

              <fieldset className="directories-panel__group">
                <legend>接続試験（保存しません）</legend>
                <p className="hint">
                  編集中の値で試します。ユーザー名を入れると検索まで、パスワードも入れると本人としての認証とロールの判定まで試します。
                </p>
                <div className="form-grid">
                  <label>
                    試すユーザー名
                    <input
                      autoComplete="off"
                      value={testUser.username}
                      onChange={(e) => setTestUser({ ...testUser, username: e.target.value })}
                    />
                  </label>
                  <label>
                    試すユーザーのパスワード
                    <input
                      type="password"
                      autoComplete="off"
                      value={testUser.password}
                      onChange={(e) => setTestUser({ ...testUser, password: e.target.value })}
                    />
                  </label>
                  <div className="directories-panel__test-button">
                    <button type="button" className="btn btn--gray" onClick={() => void runTest()}>
                      接続試験
                    </button>
                  </div>
                </div>
                {testResult && <DirectoryTestResult result={testResult} />}
              </fieldset>

              <div className="actions">
                <button type="submit" className="btn btn--filled" disabled={!canSave}>
                  {editing.mode === 'create' ? '追加' : '保存'}
                </button>
                <button type="button" className="btn btn--gray" onClick={close}>
                  キャンセル
                </button>
              </div>
            </form>
          </section>
        )}
      </fieldset>
    </div>
  )
}
