import { useCallback, useEffect, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { eventTypeGuideListSchema, type EventTypeGuideRow } from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'

type Draft = {
  general_meaning: string
  typical_causes: string
  remediation: string
}

function rowToDraft(r: EventTypeGuideRow): Draft {
  return {
    general_meaning: r.general_meaning ?? '',
    typical_causes: r.typical_causes ?? '',
    remediation: r.remediation ?? '',
  }
}

/**
 * 設定タブ「種別ガイド」: イベント種別ごとの意味・原因・対処の登録・編集。
 */
export function EventTypeGuidesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<EventTypeGuideRow[]>([])
  const [newType, setNewType] = useState('')
  const [newMeaning, setNewMeaning] = useState('')
  const [newCauses, setNewCauses] = useState('')
  const [newRemediation, setNewRemediation] = useState('')
  const [draft, setDraft] = useState<Record<number, Draft>>({})

  const load = useCallback(async () => {
    onError(null)
    try {
      const data = await apiGet<unknown>('/api/event-type-guides')
      const parsed = eventTypeGuideListSchema.parse(data)
      setList(parsed)
      const d: Record<number, Draft> = {}
      for (const r of parsed) {
        d[r.id] = rowToDraft(r)
      }
      setDraft(d)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [onError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  const add = async () => {
    const et = newType.trim()
    if (!et) {
      onError('イベント種別を入力してください')
      return
    }
    onError(null)
    try {
      await apiPost('/api/event-type-guides', {
        event_type: et,
        general_meaning: newMeaning.trim() || null,
        typical_causes: newCauses.trim() || null,
        remediation: newRemediation.trim() || null,
      })
      setNewType('')
      setNewMeaning('')
      setNewCauses('')
      setNewRemediation('')
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const save = async (id: number) => {
    onError(null)
    const row = draft[id]
    if (!row) return
    try {
      await apiPatch(`/api/event-type-guides/${id}`, {
        general_meaning: row.general_meaning.trim() || null,
        typical_causes: row.typical_causes.trim() || null,
        remediation: row.remediation.trim() || null,
      })
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const remove = async (id: number) => {
    if (!confirm('この種別のガイドを削除しますか？')) return
    onError(null)
    try {
      await apiDelete(`/api/event-type-guides/${id}`)
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        イベント種別（event_type、収集ログの種別文字列と完全一致）ごとに、一般的な意味・想定される原因・対処方法を登録します。イベント一覧では、登録がある種別にガイドを表示できます。
      </p>

      <h2>追加</h2>
      <div className="form-grid score-rules-form event-type-guides-form">
        <label>
          イベント種別（完全一致）
          <input
            value={newType}
            onChange={(e) => setNewType(e.target.value)}
            placeholder="例: vim.event.VmPoweredOnEvent"
            autoComplete="off"
          />
        </label>
        <label>
          一般的な意味
          <textarea
            value={newMeaning}
            onChange={(e) => setNewMeaning(e.target.value)}
            rows={3}
            maxLength={8000}
            placeholder="このイベントが示すこと"
          />
        </label>
        <label>
          想定される原因
          <textarea
            value={newCauses}
            onChange={(e) => setNewCauses(e.target.value)}
            rows={3}
            maxLength={8000}
          />
        </label>
        <label>
          対処方法
          <textarea
            value={newRemediation}
            onChange={(e) => setNewRemediation(e.target.value)}
            rows={3}
            maxLength={8000}
          />
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <table className="table event-type-guides-table">
        <thead>
          <tr>
            <th>イベント種別</th>
            <th>意味 / 原因 / 対処</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id}>
              <td className="msg event-type-guides-type-cell">{r.event_type}</td>
              <td className="event-type-guides-edit-cells">
                <label>
                  一般的な意味
                  <textarea
                    className="event-type-guides-textarea"
                    aria-label={`${r.event_type} の一般的な意味`}
                    value={draft[r.id]?.general_meaning ?? ''}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        [r.id]: { ...(prev[r.id] ?? rowToDraft(r)), general_meaning: e.target.value },
                      }))
                    }
                    rows={2}
                    maxLength={8000}
                  />
                </label>
                <label>
                  想定される原因
                  <textarea
                    className="event-type-guides-textarea"
                    aria-label={`${r.event_type} の想定される原因`}
                    value={draft[r.id]?.typical_causes ?? ''}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        [r.id]: { ...(prev[r.id] ?? rowToDraft(r)), typical_causes: e.target.value },
                      }))
                    }
                    rows={2}
                    maxLength={8000}
                  />
                </label>
                <label>
                  対処方法
                  <textarea
                    className="event-type-guides-textarea"
                    aria-label={`${r.event_type} の対処方法`}
                    value={draft[r.id]?.remediation ?? ''}
                    onChange={(e) =>
                      setDraft((prev) => ({
                        ...prev,
                        [r.id]: { ...(prev[r.id] ?? rowToDraft(r)), remediation: e.target.value },
                      }))
                    }
                    rows={2}
                    maxLength={8000}
                  />
                </label>
              </td>
              <td className="actions">
                <button type="button" className="btn btn--filled" onClick={() => void save(r.id)}>
                  保存
                </button>
                <button type="button" className="btn btn--gray" onClick={() => void remove(r.id)}>
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
