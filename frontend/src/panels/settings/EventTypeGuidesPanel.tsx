import { useCallback, useEffect, useRef, useState } from 'react'
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api'
import {
  buildEventTypeGuidesExportPayload,
  eventTypeGuideListSchema,
  eventTypeGuidesFileSchema,
  eventTypeGuidesImportResponseSchema,
  type EventTypeGuideRow,
  type EventTypeGuidesFile,
} from '../../api/schemas'
import { downloadJsonFile } from '../../utils/downloadJsonFile'
import { toErrorMessage } from '../../utils/errors'
import { formatEventTypeGuideCollapsedPreview } from './EventTypeGuideCollapsedPreview'
import {
  formatEventTypeGuidesFileParseError,
  formatEventTypeGuidesImportApiError,
} from './eventTypeGuidesImportErrors'

function confirmDestructiveGuideImport(deleteGuidesNotInImport: boolean, guideCount: number): boolean {
  if (!deleteGuidesNotInImport) return true
  if (guideCount === 0) {
    return confirm(
      'このファイルにはガイドが含まれていません。既存のガイドをすべて削除します。よろしいですか？',
    )
  }
  return confirm('ファイルに含まれないイベント種別のガイドは削除されます。よろしいですか？')
}

type Draft = {
  general_meaning: string
  typical_causes: string
  remediation: string
  action_required: boolean
}

function rowToDraft(r: EventTypeGuideRow): Draft {
  return {
    general_meaning: r.general_meaning ?? '',
    typical_causes: r.typical_causes ?? '',
    remediation: r.remediation ?? '',
    action_required: r.action_required,
  }
}

/**
 * 設定タブ「イベント種別ガイド」: イベント種別ごとの意味・原因・対処の登録・編集。
 */
export function EventTypeGuidesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<EventTypeGuideRow[]>([])
  const [newType, setNewType] = useState('')
  const [newMeaning, setNewMeaning] = useState('')
  const [newCauses, setNewCauses] = useState('')
  const [newRemediation, setNewRemediation] = useState('')
  const [newActionRequired, setNewActionRequired] = useState(false)
  const [draft, setDraft] = useState<Record<number, Draft>>({})
  const [overwriteExisting, setOverwriteExisting] = useState(true)
  const [deleteGuidesNotInImport, setDeleteGuidesNotInImport] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

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
        action_required: newActionRequired,
      })
      setNewType('')
      setNewMeaning('')
      setNewCauses('')
      setNewRemediation('')
      setNewActionRequired(false)
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
        action_required: row.action_required,
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

  const exportToFile = () => {
    onError(null)
    try {
      const payload = buildEventTypeGuidesExportPayload(list)
      const name = `vea-event-type-guides-${new Date().toISOString().slice(0, 10)}.json`
      downloadJsonFile(name, payload)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const onImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    let parsedFile: EventTypeGuidesFile
    try {
      const text = await file.text()
      const json: unknown = JSON.parse(text)
      parsedFile = eventTypeGuidesFileSchema.parse(json)
    } catch (err) {
      onError(formatEventTypeGuidesFileParseError(err))
      return
    }

    if (!confirmDestructiveGuideImport(deleteGuidesNotInImport, parsedFile.guides.length)) {
      return
    }

    onError(null)
    try {
      const raw = await apiPost<unknown>('/api/event-type-guides/import', {
        overwrite_existing: overwriteExisting,
        delete_guides_not_in_import: deleteGuidesNotInImport,
        guides: parsedFile.guides,
      })
      try {
        eventTypeGuidesImportResponseSchema.parse(raw)
      } catch {
        onError(
          'サーバーからの応答を解釈できませんでした。アプリを最新版に更新するか、しばらくしてから再度お試しください。',
        )
        return
      }
      await load()
    } catch (err) {
      onError(formatEventTypeGuidesImportApiError(err))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        イベント種別（event_type、収集ログの種別文字列と完全一致）ごとに、一般的な意味・想定される原因・対処方法を登録します。「対処が必要」をオンにすると、概要・イベント一覧で該当行を強調します。
      </p>

      <h2>エクスポート・インポート</h2>
      <p className="hint">
        ガイドを JSON でエクスポート・インポートできます。下の「インポート時のオプション」は「ファイルからインポート」にのみ効きます。
      </p>
      <fieldset className="score-rules-import-options">
        <legend className="score-rules-import-options__legend">インポート時のオプション</legend>
        <div className="form-grid score-rules-form score-rules-import-options__grid">
          <label className="check">
            <input
              type="checkbox"
              checked={overwriteExisting}
              onChange={(ev) => setOverwriteExisting(ev.target.checked)}
              aria-label="既存の同一イベント種別を上書き"
            />
            既存の同一イベント種別を上書き
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={deleteGuidesNotInImport}
              onChange={(ev) => setDeleteGuidesNotInImport(ev.target.checked)}
              aria-label="ファイルに含まれないイベント種別のガイドを削除"
            />
            ファイルに含まれないイベント種別のガイドを削除
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
          aria-label="イベント種別ガイド JSON を選択"
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
        <label className="check">
          <input
            type="checkbox"
            checked={newActionRequired}
            onChange={(e) => setNewActionRequired(e.target.checked)}
            aria-label="対処が必要（一覧で強調）"
          />
          対処が必要（一覧で強調）
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <p className="hint event-type-guides-list__hint">
        行をクリックすると展開し、内容の編集・保存・削除ができます。
      </p>
      <ul className="event-type-guides-list">
        {list.map((r) => {
          const d = draft[r.id] ?? rowToDraft(r)
          const preview = formatEventTypeGuideCollapsedPreview(d, { maxChars: 200 })
          const summaryAria = `${r.event_type}、${d.action_required ? '要対処' : '対処不要'}、折りたたみ、クリックで展開`
          return (
            <li key={r.id} className="event-type-guides-list__item">
              <details className="event-type-guide-row">
                <summary
                  className="event-type-guide-row__summary"
                  aria-label={summaryAria}
                >
                  <span className="event-type-guide-row__disclosure" aria-hidden="true">
                    <svg
                      className="event-type-guide-row__chevron"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      aria-hidden="true"
                      focusable="false"
                    >
                      <path
                        d="M9 6l6 6-6 6"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <div className="event-type-guide-row__summary-inner">
                    <div className="event-type-guide-row__head">
                      <span className="event-type-guide-row__type msg">{r.event_type}</span>
                      {d.action_required ? (
                        <span className="event-type-guide-row__badge">要対処</span>
                      ) : null}
                    </div>
                    <p className="event-type-guide-row__preview">{preview}</p>
                  </div>
                </summary>
                <div className="event-type-guide-row__body">
                  <div className="event-type-guides-edit-cells">
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={draft[r.id]?.action_required ?? false}
                        onChange={(e) =>
                          setDraft((prev) => ({
                            ...prev,
                            [r.id]: { ...(prev[r.id] ?? rowToDraft(r)), action_required: e.target.checked },
                          }))
                        }
                        aria-label={`${r.event_type} は対処が必要`}
                      />
                      対処が必要（一覧で強調）
                    </label>
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
                  </div>
                  <div className="event-type-guide-row__actions">
                    <button type="button" className="btn btn--filled" onClick={() => void save(r.id)}>
                      保存
                    </button>
                    <button type="button" className="btn btn--gray" onClick={() => void remove(r.id)}>
                      削除
                    </button>
                  </div>
                </div>
              </details>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
