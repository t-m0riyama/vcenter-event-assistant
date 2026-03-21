import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import { eventScoreRuleRowSchema, type EventScoreRuleRow } from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'

const eventScoreRuleListSchema = z.array(eventScoreRuleRowSchema)

export function ScoreRulesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<EventScoreRuleRow[]>([])
  const [newType, setNewType] = useState('')
  const [newDelta, setNewDelta] = useState(0)
  const [draftDelta, setDraftDelta] = useState<Record<number, number>>({})

  const load = useCallback(async () => {
    onError(null)
    try {
      const data = await apiGet<unknown>('/api/event-score-rules')
      const parsed = eventScoreRuleListSchema.parse(data)
      setList(parsed)
      const d: Record<number, number> = {}
      for (const r of parsed) {
        d[r.id] = r.score_delta
      }
      setDraftDelta(d)
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
      await apiPost('/api/event-score-rules', {
        event_type: et,
        score_delta: newDelta,
      })
      setNewType('')
      setNewDelta(0)
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const save = async (id: number) => {
    onError(null)
    try {
      const v = draftDelta[id]
      await apiPatch(`/api/event-score-rules/${id}`, {
        score_delta: typeof v === 'number' && Number.isFinite(v) ? v : 0,
      })
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const remove = async (id: number) => {
    if (!confirm('このルールを削除しますか？既存イベントのスコアはルールなしのベースに戻ります。')) return
    onError(null)
    try {
      await apiDelete(`/api/event-score-rules/${id}`)
      await load()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。最終スコアは 0〜100
        に収まります。既存の取り込み済みイベントにも、ルールの保存・変更・削除時に再計算が反映されます。
      </p>
      <h2>追加</h2>
      <div className="form-grid score-rules-form">
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
          加算（負数可）
          <input
            type="number"
            value={newDelta}
            onChange={(e) => setNewDelta(Number(e.target.value))}
          />
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <table className="table">
        <thead>
          <tr>
            <th>イベント種別</th>
            <th>加算</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id}>
              <td className="msg">{r.event_type}</td>
              <td>
                <input
                  type="number"
                  className="score-rules-delta-input"
                  aria-label={`${r.event_type} の加算`}
                  value={draftDelta[r.id] ?? r.score_delta}
                  onChange={(e) =>
                    setDraftDelta((prev) => ({
                      ...prev,
                      [r.id]: Number(e.target.value),
                    }))
                  }
                />
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
