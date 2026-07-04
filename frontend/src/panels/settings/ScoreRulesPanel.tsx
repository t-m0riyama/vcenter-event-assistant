import { useCallback, useState } from 'react'
import './ScoreRulesPanel.css'

import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import {
  buildScoreRulesExportPayload,
  eventScoreRuleListSchema,
  eventScoreRulesFileSchema,
  eventScoreRulesImportResponseSchema,
  type EventScoreRuleRow,
} from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'
import {
  formatScoreRulesFileParseError,
  formatScoreRulesImportApiError,
} from './scoreRulesImportErrors'
import { SCORE_RULES_DESTRUCTIVE_IMPORT_MESSAGES } from './importExport/confirmDestructiveImport'
import { useSettingsJsonImportExport } from './importExport/useSettingsJsonImportExport'
import { useSettingsListWithDrafts } from './useSettingsListCrud'

/** イベントスコアルール設定パネル。 */
export function ScoreRulesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [newType, setNewType] = useState('')
  const [newDelta, setNewDelta] = useState(0)

  const fetchList = useCallback(async () => {
    const data = await apiGet<unknown>('/api/event-score-rules')
    return eventScoreRuleListSchema.parse(data)
  }, [])

  const rowsToDrafts = useCallback((rows: readonly EventScoreRuleRow[]) => {
    const d: Record<number, number> = {}
    for (const r of rows) {
      d[r.id] = r.score_delta
    }
    return d
  }, [])

  const { list, drafts: draftDelta, setDrafts: setDraftDelta, load } = useSettingsListWithDrafts({
    onError,
    fetchList,
    rowsToDrafts,
  })

  const importExport = useSettingsJsonImportExport({
    exportFilenamePrefix: 'vea-score-rules',
    buildExportPayload: () => buildScoreRulesExportPayload(list),
    fileSchema: eventScoreRulesFileSchema,
    getImportItemCount: (file) => file.rules.length,
    buildImportRequestBody: (file, options) => ({
      overwrite_existing: options.overwriteExisting,
      delete_rules_not_in_import: options.deleteNotInImport,
      rules: file.rules,
    }),
    importPath: '/api/event-score-rules/import',
    importResponseSchema: eventScoreRulesImportResponseSchema,
    destructiveMessages: SCORE_RULES_DESTRUCTIVE_IMPORT_MESSAGES,
    formatFileParseError: formatScoreRulesFileParseError,
    formatImportApiError: formatScoreRulesImportApiError,
    onError,
    onImportComplete: load,
  })

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
        イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値をサーバーに保存します。最終スコアは
        0〜100 に収まり、ルールの保存・変更・削除は既存の取り込み済みイベントの再計算にも反映されます。
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
              checked={importExport.overwriteExisting}
              onChange={(e) => importExport.setOverwriteExisting(e.target.checked)}
              aria-label="既存の同一イベント種別を上書き"
            />
            既存の同一イベント種別を上書き
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={importExport.deleteNotInImport}
              onChange={(e) => importExport.setDeleteNotInImport(e.target.checked)}
              aria-label="ファイルに含まれないイベント種別のルールを削除"
            />
            ファイルに含まれないイベント種別のルールを削除
          </label>
        </div>
      </fieldset>
      <div className="score-rules-file-actions">
        <button type="button" className="btn btn--gray" onClick={importExport.exportToFile}>
          ファイルにエクスポート
        </button>
        <input
          ref={importExport.fileInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden-file-input"
          aria-label="スコアルール JSON を選択"
          onChange={(ev) => void importExport.onImportFileChange(ev)}
        />
        <button
          type="button"
          className="btn btn--filled"
          onClick={importExport.openImportFilePicker}
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
