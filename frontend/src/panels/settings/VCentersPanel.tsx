import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { getInventoryStatus } from '../../api/inventory'
import { vcenterSchema, type InventoryStatusResponse, type InventoryVCenterStatus, type VCenter } from '../../api/schemas'
import { useAuth } from '../../auth/useAuth'
import { CollectionFailure, CurrentCollectionFailure } from '../../components/CollectionFailure'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { getCollectionFailureState } from '../../utils/collectionFailureState'
import { toErrorMessage } from '../../utils/errors'

const vcenterListSchema = z.array(vcenterSchema)
type VCenterProtocol = VCenter['protocol']
type VCenterFormState = {
  name: string
  host: string
  protocol: VCenterProtocol
  port: number
  username: string
  password: string
  verify_ssl: boolean
  is_enabled: boolean
}

/** vCenter 接続設定パネル。 */
export function VCentersPanel({ onError }: { onError: (e: string | null) => void }) {
  const { hasRole } = useAuth()
  const { timeZone } = useTimeZone()
  // 登録・編集・削除は admin、接続テストは operator 以上（サーバの権限と同じ）
  const canEdit = hasRole('admin')
  const canTest = hasRole('operator')
  const [list, setList] = useState<VCenter[] | null>(null)
  const [inventoryLoad, setInventoryLoad] = useState<{
    list: VCenter[]
    result: InventoryStatusResponse | 'error'
  } | null>(null)
  const inventory = inventoryLoad?.list === list ? inventoryLoad.result : null
  const inventoryById = new Map(inventory && inventory !== 'error'
    ? inventory.vcenters.map((status) => [status.vcenter_id, status])
    : [])
  const [form, setForm] = useState<VCenterFormState>({
    name: '',
    host: '',
    protocol: 'https',
    port: 443,
    username: '',
    password: '',
    verify_ssl: true,
    is_enabled: true,
  })

  // 編集中の vCenter ID（null なら編集モードでない）
  const [editingId, setEditingId] = useState<string | null>(null)

  // 編集フォームの値
  const [editForm, setEditForm] = useState<VCenterFormState>({
    name: '',
    host: '',
    protocol: 'https',
    port: 443,
    username: '',
    password: '',
    verify_ssl: true,
    is_enabled: true,
  })

  const load = useCallback(async () => {
    onError(null)
    try {
      const data = await apiGet<unknown>('/api/vcenters')
      setList(vcenterListSchema.parse(data))
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [onError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  useEffect(() => {
    // 一覧の読み込みが成功したときと、登録・編集・削除などで一覧を取り直したときに収集状態も更新する。
    if (!list) return
    let cancelled = false
    void getInventoryStatus().then(
      (status) => { if (!cancelled) setInventoryLoad({ list, result: status }) },
      () => { if (!cancelled) setInventoryLoad({ list, result: 'error' }) },
    )
    return () => { cancelled = true }
  }, [list])

  const add = async () => {
    onError(null)
    try {
      await apiPost('/api/vcenters', form)
      setForm({
        name: '',
        host: '',
        protocol: 'https',
        port: 443,
        username: '',
        password: '',
        verify_ssl: true,
        is_enabled: true,
      })
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const remove = async (id: string) => {
    if (!confirm('削除しますか？')) return
    onError(null)
    try {
      await apiDelete(`/api/vcenters/${id}`)
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const toggleEnabled = async (v: VCenter) => {
    const msg = v.is_enabled ? '無効にしますか？' : '有効にしますか？'
    if (!confirm(msg)) return
    onError(null)
    try {
      await apiPatch(`/api/vcenters/${v.id}`, {
        is_enabled: !v.is_enabled,
      })
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const test = async (id: string) => {
    onError(null)
    try {
      const r = await apiGet<Record<string, unknown>>(`/api/vcenters/${id}/test`)
      const recommend = r.recommend_ssl_verification === true
      const recommendMsg =
        typeof r.recommend_ssl_verification_message === 'string'
          ? r.recommend_ssl_verification_message
          : '本番環境では SSL 証明書検証（verify_ssl）を有効にすることを推奨します。'
      if (recommend) {
        alert(`${recommendMsg}\n\n接続テスト結果:\n${JSON.stringify(r, null, 2)}`)
      } else {
        alert(JSON.stringify(r, null, 2))
      }
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const startEdit = (v: VCenter) => {
    setEditingId(v.id)
    setEditForm({
      name: v.name,
      host: v.host,
      protocol: v.protocol,
      port: v.port,
      username: v.username,
      password: '', // パスワードは API レスポンスに含まれない
      verify_ssl: v.verify_ssl,
      is_enabled: v.is_enabled,
    })
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const saveEdit = async () => {
    if (!editingId) return
    onError(null)
    try {
      // パスワードが空の場合はリクエストから除外（既存値を保持）
      const body: Record<string, unknown> = {
        name: editForm.name,
        host: editForm.host,
        protocol: editForm.protocol,
        port: editForm.port,
        username: editForm.username,
        verify_ssl: editForm.verify_ssl,
        is_enabled: editForm.is_enabled,
      }
      if (editForm.password) {
        body.password = editForm.password
      }
      await apiPatch(`/api/vcenters/${editingId}`, body)
      setEditingId(null)
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        vCenter の接続先と認証情報をサーバーに保存します。パスワードは暗号化して保存されます。イベントの収集と接続確認の対象となるのは、有効にした接続のみです。
      </p>
      {canEdit && (
        <>
          <h2>登録</h2>
          <div className="form-grid">
            <label>
              表示名
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>
            <label>
              ホスト
              <input
                value={form.host}
                onChange={(e) => setForm({ ...form, host: e.target.value })}
              />
            </label>
            <label>
              プロトコル
              <select
                value={form.protocol}
                onChange={(e) =>
                  setForm({
                    ...form,
                    protocol: e.target.value === 'http' ? 'http' : 'https',
                    verify_ssl: e.target.value === 'http' ? false : form.verify_ssl,
                  })
                }
              >
                <option value="https">HTTPS</option>
                <option value="http">HTTP</option>
              </select>
            </label>
            <label>
              ポート
              <input
                type="number"
                value={form.port}
                onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
              />
            </label>
            <label>
              ユーザー
              <input
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
              />
            </label>
            <label>
              パスワード
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={form.protocol === 'https' && form.verify_ssl}
                disabled={form.protocol !== 'https'}
                onChange={(e) => setForm({ ...form, verify_ssl: e.target.checked })}
              />
              SSL 証明書を検証（HTTPS のみ）
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={form.is_enabled}
                onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })}
              />
              有効
            </label>
          </div>
          <button type="button" className="btn btn--filled" onClick={() => void add()}>
            追加
          </button>
        </>
      )}

      <h2>一覧</h2>
      {inventory === 'error' && <p className="hint" role="note">関係の収集状態を読み込めませんでした。</p>}
      {inventory && inventory !== 'error' && !inventory.enabled && <p className="hint" role="note">関係の収集は無効です。</p>}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>名前</th>
              <th>ホスト</th>
              <th>SSL 検証</th>
              <th>有効</th>
              <th>ユーザー</th>
              <th>関係の収集</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list?.map((v) =>
              editingId === v.id ? (
                <tr key={v.id}>
                  <td>
                    <input
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      aria-label="表示名"
                    />
                  </td>
                  <td>
                    <select
                      value={editForm.protocol}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          protocol: e.target.value === 'http' ? 'http' : 'https',
                          verify_ssl: e.target.value === 'http' ? false : editForm.verify_ssl,
                        })
                      }
                      aria-label="プロトコル"
                      style={{ display: 'inline', width: '34%', marginRight: '4px' }}
                    >
                      <option value="https">HTTPS</option>
                      <option value="http">HTTP</option>
                    </select>
                    <input
                      value={editForm.host}
                      onChange={(e) => setEditForm({ ...editForm, host: e.target.value })}
                      aria-label="ホスト"
                      style={{ display: 'inline', width: '40%', marginRight: '4px' }}
                    />
                    :
                    <input
                      type="number"
                      value={editForm.port}
                      onChange={(e) => setEditForm({ ...editForm, port: Number(e.target.value) })}
                      aria-label="ポート"
                      style={{ display: 'inline', width: '22%', marginLeft: '4px' }}
                    />
                  </td>
                  <td>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={editForm.protocol === 'https' && editForm.verify_ssl}
                        disabled={editForm.protocol !== 'https'}
                        onChange={(e) =>
                          setEditForm({ ...editForm, verify_ssl: e.target.checked })
                        }
                      />
                    </label>
                  </td>
                  <td>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={editForm.is_enabled}
                        onChange={(e) => setEditForm({ ...editForm, is_enabled: e.target.checked })}
                      />
                    </label>
                  </td>
                  <td>
                    <input
                      value={editForm.username}
                      onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                      aria-label="ユーザー"
                      placeholder="ユーザー名"
                      style={{ marginBottom: '4px', width: '100%', boxSizing: 'border-box' }}
                    />
                    <input
                      type="password"
                      value={editForm.password}
                      onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                      aria-label="パスワード"
                      placeholder="パスワード（変更しない場合は空欄）"
                      style={{ width: '100%', boxSizing: 'border-box' }}
                    />
                  </td>
                  <td><InventoryStatusCell
                    status={inventoryById.get(v.id)}
                    availability={inventory === 'error' ? 'error' : inventory ? 'ready' : 'loading'}
                    connectionEnabled={v.is_enabled}
                    timeZone={timeZone}
                  /></td>
                  <td className="actions">
                    <button type="button" className="btn btn--filled" onClick={() => void saveEdit()}>
                      保存
                    </button>
                    <button type="button" className="btn btn--gray" onClick={cancelEdit}>
                      キャンセル
                    </button>
                  </td>
                </tr>
              ) : (
                <tr key={v.id}>
                  <td>{v.name}</td>
                  <td>
                    {v.protocol}://{v.host}:{v.port}
                  </td>
                  <td>{v.protocol === 'https' && v.verify_ssl ? 'はい' : 'いいえ'}</td>
                  <td>{v.is_enabled ? 'はい' : 'いいえ'}</td>
                  <td>{v.username}</td>
                  <td><InventoryStatusCell
                    status={inventoryById.get(v.id)}
                    availability={inventory === 'error' ? 'error' : inventory ? 'ready' : 'loading'}
                    connectionEnabled={v.is_enabled}
                    timeZone={timeZone}
                  /></td>
                  <td className="actions">
                    {canTest && (
                      <button type="button" className="btn btn--gray" onClick={() => void test(v.id)}>
                        接続テスト
                      </button>
                    )}
                    {canEdit && (
                      <>
                        <button type="button" className="btn btn--gray" onClick={() => startEdit(v)}>
                          編集
                        </button>
                        <button
                          type="button"
                          className="btn btn--gray"
                          onClick={() => void toggleEnabled(v)}
                        >
                          {v.is_enabled ? '無効' : '有効'}
                        </button>
                        <button type="button" className="btn btn--danger" onClick={() => void remove(v.id)}>
                          削除
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function InventoryStatusCell({
  status, availability, connectionEnabled, timeZone,
}: {
  status?: InventoryVCenterStatus
  availability: 'ready' | 'loading' | 'error'
  connectionEnabled: boolean
  timeZone: string
}) {
  const disabled = !(status?.is_enabled ?? connectionEnabled)
  if (!status) {
    const message = { ready: '—', loading: '読み込み中…', error: '取得できません' }[availability]
    return (
      <div className="vcenter-inventory-status">
        {disabled && <div>接続が無効のため収集しません</div>}
        <div>{message}</div>
      </div>
    )
  }

  const showTime = (at: string | null) => at ? <time dateTime={at}>{formatIsoInTimeZone(at, timeZone)}</time> : '—'
  const { last_success_at, last_failure_at, last_error, last_warning, last_warning_at, object_count, relation_count } = status
  const failureState = getCollectionFailureState(last_success_at, last_failure_at)

  return (
    <div className="vcenter-inventory-status">
      {failureState === 'current' && <CurrentCollectionFailure />}
      {disabled && <div>接続が無効のため収集しません</div>}
      <div>最後の成功 {last_success_at ? showTime(last_success_at) : '未収集'}</div>
      <CollectionFailure
        state={failureState}
        targetName={status.vcenter_name}
        lastSuccessAt={last_success_at}
        lastFailureAt={last_failure_at}
        error={last_error}
        timeZone={timeZone}
        showFailureTime
        hideCurrentLabel
      />
      {(last_warning_at || last_warning) && (
        <div>警告 {showTime(last_warning_at)}{last_warning && <div>{last_warning}</div>}</div>
      )}
      <div>管理対象 {object_count ?? '—'} 件、関係 {relation_count ?? '—'} 件</div>
    </div>
  )
}
