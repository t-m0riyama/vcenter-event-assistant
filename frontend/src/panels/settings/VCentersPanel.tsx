import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { vcenterSchema, type VCenter } from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'

const vcenterListSchema = z.array(vcenterSchema)

export function VCentersPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<VCenter[]>([])
  const [form, setForm] = useState({
    name: '',
    host: '',
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
      setForm({ name: '', host: '', port: 443, username: '', password: '', is_enabled: true })
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
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((v) => (
            <tr key={v.id}>
              <td>{v.name}</td>
              <td>
                {v.host}:{v.port}
              </td>
              <td>{v.is_enabled ? 'はい' : 'いいえ'}</td>
              <td className="actions">
                <button type="button" className="btn btn--gray" onClick={() => void test(v.id)}>
                  接続テスト
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
          ))}
        </tbody>
      </table>
    </div>
  )
}
