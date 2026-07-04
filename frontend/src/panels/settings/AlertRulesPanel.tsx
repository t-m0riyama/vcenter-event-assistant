import { Fragment, useCallback, useState } from 'react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../../api'
import {
  alertRuleRowSchema,
  alertRulesFileSchema,
  alertRulesImportResponseSchema,
  buildAlertRulesExportPayload,
  type AlertRuleRow,
} from '../../api/schemas'
import { toErrorMessage } from '../../utils/errors'
import {
  formatAlertRulesFileParseError,
  formatAlertRulesImportApiError,
} from './alertRulesImportErrors'
import { KNOWN_METRIC_KEYS } from '../../metrics/knownMetricKeys'
import { DEFAULT_ALERT_METRIC_KEY } from './alertRuleDefaults'
import { ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES } from './importExport/confirmDestructiveImport'
import { useSettingsJsonImportExport } from './importExport/useSettingsJsonImportExport'
import { useSettingsListFetch } from './useSettingsListCrud'
import './AlertRulesPanel.css'

type AlertLevel = 'critical' | 'error' | 'warning'

const ALERT_LEVEL_LABELS: Record<AlertLevel, string> = {
  critical: 'クリティカル',
  error: 'エラー',
  warning: '警告',
}

type AlertRule = AlertRuleRow & {
  config: {
    threshold?: number
    metric_key?: string
    cooldown_minutes?: number
  }
}

interface EditDraft {
  name: string
  threshold: number
  metric_key: string
  cooldown_minutes: number
}

/**
 * アラートルールの一覧・新規作成・レベル変更（PATCH）・有効切替・削除を行う設定パネル。
 */
export function AlertRulesPanel({ onError }: { onError: (msg: string) => void }) {
  const fetchList = useCallback(async () => {
    const data = await apiGet<unknown>('/api/alerts/rules')
    const parsed = alertRuleRowSchema.array().parse(data)
    return parsed as AlertRule[]
  }, [])

  const { list: rules, loading, load: fetchRules } = useSettingsListFetch({
    onError,
    fetchList,
  })

  const [isAdding, setIsAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<'event_score' | 'metric_threshold'>('event_score')
  const [newAlertLevel, setNewAlertLevel] = useState<AlertLevel>('warning')
  const [newThreshold, setNewThreshold] = useState(60)
  const [newMetricKey, setNewMetricKey] = useState<string>(DEFAULT_ALERT_METRIC_KEY)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [drafts, setDrafts] = useState<Record<number, EditDraft>>({})

  const importExport = useSettingsJsonImportExport({
    exportFilenamePrefix: 'vea-alert-rules',
    buildExportPayload: () => buildAlertRulesExportPayload(rules),
    fileSchema: alertRulesFileSchema,
    getImportItemCount: (file) => file.rules.length,
    buildImportRequestBody: (file, options) => ({
      overwrite_existing: options.overwriteExisting,
      delete_rules_not_in_import: options.deleteNotInImport,
      rules: file.rules,
    }),
    importPath: '/api/alerts/rules/import',
    importResponseSchema: alertRulesImportResponseSchema,
    destructiveMessages: ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES,
    formatFileParseError: formatAlertRulesFileParseError,
    formatImportApiError: formatAlertRulesImportApiError,
    onError: (msg) => onError(msg ?? ''),
    onImportComplete: fetchRules,
  })

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const config = newType === 'event_score' 
        ? { threshold: newThreshold, cooldown_minutes: 10 }
        : { metric_key: newMetricKey, threshold: newThreshold }
      
      await apiPost('/api/alerts/rules', {
        name: newName,
        rule_type: newType,
        alert_level: newAlertLevel,
        config,
      })
      setNewName('')
      setIsAdding(false)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const handleLevelChange = async (rule: AlertRule, level: AlertLevel) => {
    if (rule.alert_level === level) return
    try {
      await apiPatch(`/api/alerts/rules/${rule.id}`, { alert_level: level })
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const handleToggle = async (rule: AlertRule) => {
    try {
      await apiPatch(`/api/alerts/rules/${rule.id}`, {
        is_enabled: !rule.is_enabled
      })
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('このアラートルールを削除しますか？')) return
    try {
      await apiDelete(`/api/alerts/rules/${id}`)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const makeDraftFromRule = (rule: AlertRule): EditDraft => ({
    name: rule.name,
    threshold: Number(rule.config.threshold ?? 0),
    metric_key: rule.config.metric_key ?? '',
    cooldown_minutes: Number(rule.config.cooldown_minutes ?? 10),
  })

  const updateDraft = (ruleId: number, patch: Partial<EditDraft>) => {
    setDrafts((prev) => {
      const currentRule = rules.find((rule) => rule.id === ruleId)
      if (!currentRule) return prev
      const base = prev[ruleId] ?? makeDraftFromRule(currentRule)
      return { ...prev, [ruleId]: { ...base, ...patch } }
    })
  }

  const handleExpandRow = (rule: AlertRule) => {
    setExpandedId((prev) => (prev === rule.id ? null : rule.id))
    setDrafts((prev) => (prev[rule.id] ? prev : { ...prev, [rule.id]: makeDraftFromRule(rule) }))
  }

  const handleCancelEdit = (ruleId: number) => {
    setExpandedId(null)
    setDrafts((prev) => {
      const next = { ...prev }
      delete next[ruleId]
      return next
    })
  }

  const isDraftChanged = (rule: AlertRule, draft: EditDraft): boolean => {
    if (draft.name.trim() !== rule.name) return true
    if (Number(rule.config.threshold ?? 0) !== draft.threshold) return true
    if (rule.rule_type === 'metric_threshold') return (rule.config.metric_key ?? '') !== draft.metric_key
    return Number(rule.config.cooldown_minutes ?? 10) !== draft.cooldown_minutes
  }

  const handleSaveEdit = async (rule: AlertRule) => {
    const draft = drafts[rule.id] ?? makeDraftFromRule(rule)
    const nextName = draft.name.trim()
    if (!nextName) {
      onError('ルール名は必須です。')
      return
    }
    if (!Number.isFinite(draft.threshold)) {
      onError('閾値には数値を入力してください。')
      return
    }

    const nextConfig: AlertRule['config'] = { ...rule.config, threshold: draft.threshold }
    if (rule.rule_type === 'metric_threshold') nextConfig.metric_key = draft.metric_key.trim()
    if (rule.rule_type === 'event_score') nextConfig.cooldown_minutes = draft.cooldown_minutes

    try {
      await apiPatch(`/api/alerts/rules/${rule.id}`, { name: nextName, config: nextConfig })
      handleCancelEdit(rule.id)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  if (loading) return <div className="loading">アラートルールを読み込み中…</div>

  return (
    <div className="panel alert-rules-panel">
      <div className="alert-rules-panel-header">
        <p className="hint">
          イベントスコアやメトリクスに基づくアラート判定ルールをサーバーに保存します。判定対象になるのは有効化したルールだけです。
        </p>
        <button type="button" className="btn btn--filled" onClick={() => setIsAdding(true)}>
          新規ルール追加
        </button>
      </div>
      <h2>エクスポート・インポート</h2>
      <p className="hint">
        アラートルールを JSON でエクスポート・インポートできます。下の「インポート時のオプション」は「ファイルからインポート」にのみ効きます。
      </p>
      <fieldset className="score-rules-import-options">
        <legend className="score-rules-import-options__legend">インポート時のオプション</legend>
        <div className="form-grid score-rules-import-options__grid">
          <label className="check">
            <input
              type="checkbox"
              checked={importExport.overwriteExisting}
              onChange={(event) => importExport.setOverwriteExisting(event.target.checked)}
              aria-label="既存の同一ルール名を上書き"
            />
            既存の同一ルール名を上書き
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={importExport.deleteNotInImport}
              onChange={(event) => importExport.setDeleteNotInImport(event.target.checked)}
              aria-label="ファイルに含まれないアラートルールを削除"
            />
            ファイルに含まれないアラートルールを削除
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
          aria-label="アラートルール JSON を選択"
          onChange={(event) => void importExport.onImportFileChange(event)}
        />
        <button
          type="button"
          className="btn btn--filled"
          onClick={importExport.openImportFilePicker}
        >
          ファイルからインポート
        </button>
      </div>

      {isAdding && (
        <form className="add-rule-form" onSubmit={handleAdd}>
          <h3>新規ルールの作成</h3>
          <div className="form-grid">
            <label>
              ルール名
              <input 
                type="text" 
                value={newName} 
                onChange={(e) => setNewName(e.target.value)} 
                placeholder="例: 高負荷CPUアラート"
                required 
              />
            </label>
            <label>
              タイプ
              <select value={newType} onChange={(e) => setNewType(e.target.value as 'event_score' | 'metric_threshold')}>
                <option value="event_score">イベントスコア</option>
                <option value="metric_threshold">メトリクス閾値</option>
              </select>
            </label>
            <label>
              レベル
              <select
                value={newAlertLevel}
                onChange={(e) => setNewAlertLevel(e.target.value as AlertLevel)}
                title="クリティカル: すぐ対処 / エラー: 対処必須 / 警告: 検討"
              >
                <option value="critical">{ALERT_LEVEL_LABELS.critical}</option>
                <option value="error">{ALERT_LEVEL_LABELS.error}</option>
                <option value="warning">{ALERT_LEVEL_LABELS.warning}</option>
              </select>
            </label>

            {newType === 'metric_threshold' && (
              <label>
                メトリクスキー
                <input
                  type="text"
                  list="alert-metric-key-options"
                  value={newMetricKey}
                  onChange={(e) => setNewMetricKey(e.target.value)}
                  placeholder={DEFAULT_ALERT_METRIC_KEY}
                />
                <datalist id="alert-metric-key-options">
                  {KNOWN_METRIC_KEYS.map((key) => (
                    <option key={key} value={key} />
                  ))}
                </datalist>
              </label>
            )}

            <label>
              閾値
              <input 
                type="number" 
                value={newThreshold} 
                onChange={(e) => setNewThreshold(Number(e.target.value))} 
                required 
              />
            </label>
          </div>

          <div className="form-actions">
            <button type="submit" className="btn btn--filled">保存</button>
            <button type="button" className="btn btn--gray" onClick={() => setIsAdding(false)}>キャンセル</button>
          </div>
        </form>
      )}

      <table className="table">
        <thead>
          <tr>
            <th>名前</th>
            <th>タイプ</th>
            <th>条件</th>
            <th>レベル</th>
            <th>有効</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rules.length === 0 ? (
            <tr>
              <td colSpan={6} className="hint">ルールが設定されていません。</td>
            </tr>
          ) : (
            rules.map((r) => {
              const draft = drafts[r.id] ?? makeDraftFromRule(r)
              const expanded = expandedId === r.id
              const changed = isDraftChanged(r, draft)
              const editRowId = `alert-rule-edit-row-${r.id}`
              return (
                <Fragment key={r.id}>
                  <tr
                    className={`${r.is_enabled ? '' : 'disabled-row'} editable-row ${expanded ? 'expanded-row' : ''}`}
                  >
                    <td>
                      <button
                        type="button"
                        className="btn btn--gray"
                        aria-expanded={expanded}
                        aria-controls={editRowId}
                        aria-label={expanded ? `${r.name} の編集を閉じる` : `${r.name} の編集を開く`}
                        onClick={() => handleExpandRow(r)}
                      >
                        {expanded ? '▾' : '▸'}
                      </button>{' '}
                      {r.name}
                    </td>
                    <td>{r.rule_type === 'event_score' ? 'イベント' : 'メトリクス'}</td>
                    <td>
                      {r.rule_type === 'event_score' ? (
                        <span>スコア {r.config.threshold} 以上</span>
                      ) : (
                        <span>{r.config.metric_key} ≥ {r.config.threshold}</span>
                      )}
                    </td>
                    <td className="col-level">
                      <select
                        className="alert-level-select"
                        value={r.alert_level}
                        onChange={(e) => void handleLevelChange(r, e.target.value as AlertLevel)}
                        aria-label={`${r.name} のアラートレベル`}
                      >
                        <option value="critical">{ALERT_LEVEL_LABELS.critical}</option>
                        <option value="error">{ALERT_LEVEL_LABELS.error}</option>
                        <option value="warning">{ALERT_LEVEL_LABELS.warning}</option>
                      </select>
                    </td>
                    <td>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={r.is_enabled}
                          onChange={() => handleToggle(r)}
                          aria-label={`${r.name} を${r.is_enabled ? '無効化' : '有効化'}`}
                        />
                      </label>
                    </td>
                    <td className="actions">
                      <button type="button" className="btn btn--gray" onClick={() => handleDelete(r.id)}>削除</button>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr id={editRowId} className="edit-row">
                      <td colSpan={6}>
                        <div className="form-grid">
                          <label>
                            ルール名
                            <input
                              type="text"
                              value={draft.name}
                              onChange={(e) => updateDraft(r.id, { name: e.target.value })}
                              aria-label={`${r.name} のルール名`}
                            />
                          </label>
                          <label>
                            閾値
                            <input
                              type="number"
                              value={draft.threshold}
                              onChange={(e) => updateDraft(r.id, { threshold: Number(e.target.value) })}
                              aria-label={`${r.name} の閾値`}
                            />
                          </label>
                          {r.rule_type === 'metric_threshold' ? (
                            <label>
                              メトリクスキー
                              <input
                                type="text"
                                list="alert-metric-key-options"
                                value={draft.metric_key}
                                onChange={(e) => updateDraft(r.id, { metric_key: e.target.value })}
                                aria-label={`${r.name} のメトリクスキー`}
                              />
                            </label>
                          ) : (
                            <label
                              title="同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで"
                            >
                              再通知間隔（分）
                              <input
                                type="number"
                                min={1}
                                value={draft.cooldown_minutes}
                                onChange={(e) => updateDraft(r.id, { cooldown_minutes: Number(e.target.value) })}
                                aria-label={`${r.name} の再通知間隔（分）。同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで`}
                              />
                            </label>
                          )}
                        </div>
                        <p className="hint edit-row-hint">
                          タイプは変更できません。変更する場合は既存ルールを削除して再作成してください。
                        </p>
                        <div className="form-actions">
                          <button type="button" className="btn btn--filled" disabled={!changed} onClick={() => void handleSaveEdit(r)}>
                            保存
                          </button>
                          <button type="button" className="btn btn--gray" onClick={() => handleCancelEdit(r.id)}>
                            キャンセル
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
