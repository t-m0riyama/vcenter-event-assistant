import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { vcenterSchema, type VCenter } from '../../api/schemas'
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
  is_enabled: boolean
}

export function VCentersPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<VCenter[]>([])
  const [form, setForm] = useState<VCenterFormState>({
    name: '',
    host: '',
    protocol: 'https',
    port: 443,
    username: '',
    password: '',
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
      alert(JSON.stringify(r, null, 2))
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
              setForm({ ...form, protocol: e.target.value === 'http' ? 'http' : 'https' })
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
            checked={form.is_enabled}
            onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })}
          />
          有効
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <table className="table">
        <thead>
          <tr>
            <th>名前</th>
            <th>ホスト</th>
            <th>有効</th>
            <th>ユーザー</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((v) =>
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
                <td>{v.is_enabled ? 'はい' : 'いいえ'}</td>
                <td>{v.username}</td>
                <td className="actions">
                  <button type="button" className="btn btn--gray" onClick={() => void test(v.id)}>
                    接続テスト
                  </button>
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
                  <button type="button" className="btn btn--gray" onClick={() => void remove(v.id)}>
                    削除
                  </button>
                </td>
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  )
}
