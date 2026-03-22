import { useCallback, useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import {
  buildScoreRulesExportPayload,
  eventScoreRuleListSchema,
  eventScoreRulesFileSchema,
  eventScoreRulesImportResponseSchema,
  type EventScoreRuleRow,
  type EventScoreRulesFile,
} from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'
import {
  formatScoreRulesFileParseError,
  formatScoreRulesImportApiError,
} from './scoreRulesImportErrors'

function confirmDestructiveImport(deleteRulesNotInImport: boolean, ruleCount: number): boolean {
  if (!deleteRulesNotInImport) return true
  if (ruleCount === 0) {
    return confirm(
      'このファイルにはルールが含まれていません。既存のルールをすべて削除します。よろしいですか？',
    )
  }
  return confirm(
    'ファイルに含まれないイベント種別のルールは削除されます。よろしいですか？',
  )
}

function downloadJsonFile(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function ScoreRulesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<EventScoreRuleRow[]>([])
  const [newType, setNewType] = useState('')
  const [newDelta, setNewDelta] = useState(0)
  const [draftDelta, setDraftDelta] = useState<Record<number, number>>({})
  const [overwriteExisting, setOverwriteExisting] = useState(true)
  const [deleteRulesNotInImport, setDeleteRulesNotInImport] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  const exportToFile = () => {
    onError(null)
    try {
      const payload = buildScoreRulesExportPayload(list)
      const name = `vea-score-rules-${new Date().toISOString().slice(0, 10)}.json`
      downloadJsonFile(name, payload)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const onImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    let parsedFile: EventScoreRulesFile
    try {
      const text = await file.text()
      const json: unknown = JSON.parse(text)
      parsedFile = eventScoreRulesFileSchema.parse(json)
    } catch (err) {
      onError(formatScoreRulesFileParseError(err))
      return
    }

    if (!confirmDestructiveImport(deleteRulesNotInImport, parsedFile.rules.length)) {
      return
    }

    onError(null)
    try {
      const raw = await apiPost<unknown>('/api/event-score-rules/import', {
        overwrite_existing: overwriteExisting,
        delete_rules_not_in_import: deleteRulesNotInImport,
        rules: parsedFile.rules,
      })
      try {
        eventScoreRulesImportResponseSchema.parse(raw)
      } catch {
        onError(
          'サーバーからの応答を解釈できませんでした。アプリを最新版に更新するか、しばらくしてから再度お試しください。',
        )
        return
      }
      await load()
    } catch (err) {
      onError(formatScoreRulesImportApiError(err))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。最終スコアは 0〜100
        に収まります。既存の取り込み済みイベントにも、ルールの保存・変更・削除時に再計算が反映されます。
      </p>
      <h2>エクスポート・インポート</h2>
      <p className="hint">
        ルールを JSON でエクスポート・インポートできます。下の「インポート時のオプション」は「ファイルからインポート」にのみ効きます。
      </p>
      <fieldset className="score-rules-import-options">
        <legend className="score-rules-import-options__legend">インポート時のオプション</legend>
        <div className="form-grid score-rules-form score-rules-import-options__grid">
          <label className="check">
            <input
              type="checkbox"
              checked={overwriteExisting}
              onChange={(e) => setOverwriteExisting(e.target.checked)}
              aria-label="既存の同一イベント種別を上書き"
            />
            既存の同一イベント種別を上書き
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={deleteRulesNotInImport}
              onChange={(e) => setDeleteRulesNotInImport(e.target.checked)}
              aria-label="ファイルに含まれないイベント種別のルールを削除"
            />
            ファイルに含まれないイベント種別のルールを削除
          </label>
        </div>
      </fieldset>
      <div className="score-rules-file-actions">
        <button type="button" className="btn btn--gray" onClick={exportToFile}>
          ファイルにエクスポート
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden-file-input"
          aria-label="スコアルール JSON を選択"
          onChange={(ev) => void onImportFileChange(ev)}
        />
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => fileInputRef.current?.click()}
        >
          ファイルからインポート
        </button>
      </div>

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
