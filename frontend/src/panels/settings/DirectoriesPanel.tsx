import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, apiDelete, apiGet, apiPatch, apiPost, notifyUnauthorized } from '../../api'
import {
  directoryListSchema,
  directoryPolicySchema,
  directoryTestResponseSchema,
  type Directory,
  type DirectoryPolicy,
  type DirectoryTestResponse,
} from '../../api/schemas'
import { fetchMe } from '../../auth/authApi'
import { useAuth } from '../../auth/useAuth'
import { toErrorMessage } from '../../utils/errors'
import { DirectoryForm } from './DirectoryForm'
import { DirectoryTestResult } from './DirectoryTestResult'
import { DirectoryVerificationDialog } from './DirectoryVerificationDialog'
import {
  affectsLogin,
  changesFromForm,
  connectionWarnings,
  createBody,
  emptyDirectoryForm,
  formFromDirectory,
  mappingsChanged,
  mappingsFromForm,
  revokesSessions,
  type DirectoryFormState,
} from './directoryFormState'
import './DirectoriesPanel.css'

const KIND_LABELS: Record<Directory['kind'], string> = { ad: 'Active Directory', ldap: 'LDAP' }

/** 編集中の対象。新規作成か、保存済みのディレクトリか。 */
type Editing = { readonly mode: 'create' } | { readonly mode: 'edit'; readonly original: Directory }

/** 保存の前の確認でサーバが返す 409 の理由（``X-VEA-Error-Code``）。 */
const VERIFICATION_REQUIRED = 'directory_verification_required'
const VERIFICATION_FAILED = 'directory_verification_failed'

const UNTESTED_MESSAGE =
  '編集中の値での接続試験が成功していません。設定を誤ると、この後このディレクトリでログインできなくなります。このまま保存しますか？'
const LOGOUT_OTHERS_MESSAGE =
  '保存すると、このディレクトリでログイン中の利用者はログアウトされます（ローカルや別のディレクトリの利用者は影響を受けません）。保存しますか？'
const LOGOUT_SELF_MESSAGE =
  '保存すると、このディレクトリでログイン中の利用者はログアウトされます。あなたもこのディレクトリでログインしているため、ログイン画面に戻ります。保存しますか？'
const LOGGED_OUT_SELF_NOTICE = '認証ディレクトリの設定を保存したため、ログアウトしました。新しい設定でログインし直してください。'
const SELF_DISABLE_REASON =
  'あなたはこのディレクトリでログインしているため、無効にできません。ローカルや別のディレクトリの管理者でログインし直してから操作してください。'

/** 保存しようとしている変更（資格情報を求められたら、入力の後に同じ本文で送り直す）。 */
type PendingSave = {
  readonly original: Directory
  readonly body: Record<string, unknown>
  /**
   * 保存で自分のセッションも失効するおそれがあるか。サーバは対応表の DN を正規化して比べるので、
   * 実際に失効したかは保存の後に確かめる。
   */
  readonly logsOutSelf: boolean
}

function realmKeyOf(d: Directory): string {
  return `dir:${d.id}`
}

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
  const { me } = useAuth()
  const [list, setList] = useState<Directory[]>([])
  const [policy, setPolicy] = useState<DirectoryPolicy | null>(null)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [form, setForm] = useState<DirectoryFormState>(emptyDirectoryForm)
  const [testUser, setTestUser] = useState({ username: '', password: '' })
  const [testResult, setTestResult] = useState<DirectoryTestResponse | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // 接続試験が成功したときのフォームの値。これと今の値が同じなら、保存の前に試験を促さない
  const [testedForm, setTestedForm] = useState<string | null>(null)
  // 資格情報を求められている保存（ダイアログを開いている）
  const [verifying, setVerifying] = useState<(PendingSave & { readonly error: string | null }) | null>(null)

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

  /**
   * 操作を実行する。成功したら ``done`` を出して一覧を読み直す（``done`` が null なら読み直さない）。
   * 失敗は ``handleError`` が true を返さなければ画面のエラーとして出す。
   */
  const run = async <T,>(
    action: () => Promise<T>,
    done: string | null,
    handleError?: (e: unknown) => boolean,
  ): Promise<T | undefined> => {
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
      if (!handleError?.(e)) onError(toErrorMessage(e))
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
    setTestedForm(null)
    setNotice(null)
  }

  const close = () => {
    setEditing(null)
    setTestResult(null)
    setTestedForm(null)
  }

  const testCredentials = () => ({
    username: testUser.username.trim() === '' ? null : testUser.username.trim(),
    password: testUser.password === '' ? null : testUser.password,
  })

  /** 編集中の値で接続試験をする（保存しない）。 */
  const runTest = async () => {
    if (!editing) return
    setTestResult(null)
    setTestedForm(null)
    const snapshot = JSON.stringify(form)
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
    if (!result) return
    setTestResult(result)
    if (result.ok) setTestedForm(snapshot)
  }

  const testedCurrentForm = testedForm === JSON.stringify(form)

  /** 変更を送る。資格情報を求められたらダイアログを開き、入力の後に ``verification`` を付けて送り直す。 */
  const submit = async (pending: PendingSave, verification?: { username: string; password: string }) => {
    const { original, body, logsOutSelf } = pending
    const name = typeof body.name === 'string' ? body.name : original.name
    const saved = await run(
      () => apiPatch(`/api/auth/directories/${original.id}`, verification ? { ...body, verification } : body),
      // 自分のセッションも失効するおそれがあるときは、確かめてから一覧を読み直す（下）
      logsOutSelf ? null : `${name} を保存しました。`,
      (e) => {
        if (
          e instanceof ApiError &&
          e.status === 409 &&
          (e.errorCode === VERIFICATION_REQUIRED || e.errorCode === VERIFICATION_FAILED)
        ) {
          setVerifying({ ...pending, error: e.errorCode === VERIFICATION_FAILED ? e.message : null })
          return true
        }
        setVerifying(null)
        return false
      },
    )
    if (saved === undefined) return
    setVerifying(null)
    close()
    if (!logsOutSelf) return
    // 失効していれば理由を添えてログイン画面へ戻す。確かめられなかったときは読み直しに任せる
    // （失効していれば 401 で認証ゲートがログイン画面へ戻す）
    const current = await fetchMe().catch(() => undefined)
    if (current === null) {
      notifyUnauthorized(LOGGED_OUT_SELF_NOTICE)
      return
    }
    setNotice(`${name} を保存しました。`)
    await load()
  }

  const save = async () => {
    if (!editing) return
    if (!testedCurrentForm && editing.mode === 'create' && !confirm(UNTESTED_MESSAGE)) return
    if (editing.mode === 'create') {
      const ok = await run(() => apiPost('/api/auth/directories', createBody(form)), `${form.name.trim()} を追加しました。`)
      if (ok !== undefined) close()
      return
    }
    const { original } = editing
    // 設定と対応表を 1 回で送る（変えていなければ送らない）
    const changes = changesFromForm(original, form)
    const mappingsEdited = mappingsChanged(original, form)
    const body: Record<string, unknown> = { ...changes }
    if (mappingsEdited) body.mappings = mappingsFromForm(form)
    if (Object.keys(body).length === 0) {
      close()
      return
    }
    // ログインの成否に関わる変更は、先に編集中の値で試すよう促す（Issue #254）
    if (affectsLogin(changes, mappingsEdited) && !testedCurrentForm && !confirm(UNTESTED_MESSAGE)) return
    const self = me.realm === realmKeyOf(original)
    const revokes = revokesSessions(changes, mappingsEdited)
    if (revokes && !confirm(self ? LOGOUT_SELF_MESSAGE : LOGOUT_OTHERS_MESSAGE)) return
    await submit({ original, body, logsOutSelf: self && revokes })
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
          ログインに使用する Active Directory / LDAP を管理します。ユーザーのロールは、ログインのたびにグループとロールの対応表に基づいて決定されます。
          接続先・検索・グループの設定や対応表を変更した場合、またはディレクトリを無効にした場合は、そのディレクトリでログイン中のユーザーはログアウトされます。
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
          <p className="hint">ディレクトリは登録されていません。ローカルユーザーのみがログインできます。</p>
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
                // 自分がログインしているディレクトリは無効にできない（サーバも 409 で断る。Issue #254）
                disableLockedReason={
                  editing.mode === 'edit' && editing.original.is_enabled && me.realm === realmKeyOf(editing.original)
                    ? SELF_DISABLE_REASON
                    : null
                }
              />

              <fieldset className="directories-panel__group">
                <legend>接続試験（保存しません）</legend>
                <p className="hint">
                  編集中の設定値で接続を試験します。ユーザー名を入力すると、検索、ID 属性、グループの判定（割り当てられるロール）まで確認します。パスワードも入力すると、そのユーザーとしての認証も確認します。
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
      {verifying && (
        <DirectoryVerificationDialog
          directoryName={verifying.original.name}
          error={verifying.error}
          submitting={busy}
          onSubmit={(credentials) => void submit(verifying, credentials)}
          onClose={() => setVerifying(null)}
        />
      )}
    </div>
  )
}
