import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../../api'
import {
  alertRuleRowSchema,
  alertRulesFileSchema,
  alertRulesImportResponseSchema,
  buildAlertRulesExportPayload,
  type AlertRuleRow,
} from '../../api/schemas'
import { useAuth } from '../../auth/useAuth'
import { toErrorMessage } from '../../utils/errors'
import {
  formatAlertRulesFileParseError,
  formatAlertRulesImportApiError,
} from './alertRulesImportErrors'
import {
  KNOWN_METRIC_KEYS,
  installMetricCatalog,
  mergeMetricKeyOptions,
  type MetricCatalogDefinition,
} from '../../metrics/knownMetricKeys'
import { DEFAULT_ALERT_METRIC_KEY } from './alertRuleDefaults'
import { ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES } from './importExport/confirmDestructiveImport'
import { useSettingsJsonImportExport } from './importExport/useSettingsJsonImportExport'
import { useSettingsListFetch } from './useSettingsListCrud'
import './AlertRulesPanel.css'
import { SettingsListRow } from '../../components/SettingsListRow'

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
  alert_level: AlertLevel
  is_enabled: boolean
  threshold: number
  metric_key: string
  cooldown_minutes: number
}

/** レベルのバッジの色（通知履歴と同じ。クリティカルは赤、エラーは黄、警告は無彩色）。 */
const ALERT_LEVEL_BADGE_CLASS: Record<AlertLevel, string> = {
  critical: 'settings-row__badge settings-row__badge--danger',
  error: 'settings-row__badge settings-row__badge--caution',
  warning: 'settings-row__badge',
}

/**
 * アラートルールの一覧・新規作成・編集（名前・レベル・有効・閾値などを PATCH でまとめて保存）・削除を行う設定パネル。
 * 一覧はイベント種別ガイドと同じ折りたたみ行で、行を展開して編集する。
 */
export function AlertRulesPanel({ onError }: { onError: (msg: string) => void }) {
  // 追加・変更・削除・インポートは admin だけ。エクスポートは operator 以上で、viewer には出さない
  // （閲覧・詳細の展開は全ロール）
  const { hasRole } = useAuth()
  const canEdit = hasRole('admin')
  const canExport = hasRole('operator')
  const fetchList = useCallback(async () => {
    const data = await apiGet<unknown>('/api/alerts/rules')
    const parsed = alertRuleRowSchema.array().parse(data)
    return parsed as AlertRule[]
  }, [])

  const { list: rules, loading, load: fetchRules } = useSettingsListFetch({
    onError,
    fetchList,
  })

  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<'event_score' | 'metric_threshold'>('event_score')
  const [newAlertLevel, setNewAlertLevel] = useState<AlertLevel>('warning')
  const [newThreshold, setNewThreshold] = useState(60)
  const [newMetricKey, setNewMetricKey] = useState<string>(DEFAULT_ALERT_METRIC_KEY)
  const [drafts, setDrafts] = useState<Record<number, EditDraft>>({})
  const [metricKeyOptions, setMetricKeyOptions] = useState<string[]>([...KNOWN_METRIC_KEYS])

  useEffect(() => {
    void apiGet<{ metrics?: MetricCatalogDefinition[] }>('/api/metrics/catalog')
      .then((data) => {
        const definitions = Array.isArray(data.metrics) ? data.metrics : []
        installMetricCatalog(definitions)
        setMetricKeyOptions(mergeMetricKeyOptions([]))
      })
      .catch(() => undefined)
  }, [])

  const {
    overwriteExisting, setOverwriteExisting,
    deleteNotInImport, setDeleteNotInImport,
    exportToFile, fileInputRef, onImportFileChange, openImportFilePicker,
  } = useSettingsJsonImportExport({
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
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('このアラートルールを削除しますか？通知履歴と待機中の通知も削除されます。送信開始済みのメールは取り消せません。')) return
    try {
      await apiDelete(`/api/alerts/rules/${id}`)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const makeDraftFromRule = (rule: AlertRule): EditDraft => ({
    name: rule.name,
    alert_level: rule.alert_level as AlertLevel,
    is_enabled: rule.is_enabled,
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

  const discardDraft = (ruleId: number) => {
    setDrafts((prev) => {
      const next = { ...prev }
      delete next[ruleId]
      return next
    })
  }

  const isDraftChanged = (rule: AlertRule, draft: EditDraft): boolean => {
    if (draft.name.trim() !== rule.name) return true
    if (draft.alert_level !== rule.alert_level) return true
    if (draft.is_enabled !== rule.is_enabled) return true
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
      await apiPatch(`/api/alerts/rules/${rule.id}`, {
        name: nextName,
        alert_level: draft.alert_level,
        is_enabled: draft.is_enabled,
        config: nextConfig,
      })
      discardDraft(rule.id)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  if (loading) return <div className="loading">アラートルールを読み込み中…</div>

  return (
    <div className="panel alert-rules-panel">
      <p className="hint">
        イベントのスコアやメトリクスに基づくアラートの判定ルールをサーバーに保存します。判定の対象となるのは、有効にしたルールのみです。
      </p>
      {canExport && (
        <>
          <h2>{canEdit ? 'エクスポート・インポート' : 'エクスポート'}</h2>
          <p className="hint">
            {canEdit
              ? 'アラートルールを JSON 形式でエクスポート・インポートできます。下の「インポート時のオプション」は、「ファイルからインポート」の場合にのみ適用されます。'
              : 'アラートルールを JSON 形式でエクスポートできます。'}
          </p>
          {canEdit && (
            <>
              <fieldset className="score-rules-import-options">
                <legend className="score-rules-import-options__legend">インポート時のオプション</legend>
                <div className="form-grid score-rules-import-options__grid">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={overwriteExisting}
                      onChange={(event) => setOverwriteExisting(event.target.checked)}
                      aria-label="既存の同一ルール名を上書き"
                    />
                    既存の同一ルール名を上書き
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={deleteNotInImport}
                      onChange={(event) => setDeleteNotInImport(event.target.checked)}
                      aria-label="ファイルに含まれないアラートルールを削除"
                    />
                    ファイルに含まれないアラートルールを削除
                  </label>
                </div>
              </fieldset>
            </>
          )}
          <div className="score-rules-file-actions">
            <button type="button" className="btn btn--gray" onClick={exportToFile}>
              ファイルにエクスポート
            </button>
            {canEdit && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/json,.json"
                  className="hidden-file-input"
                  aria-label="アラートルール JSON を選択"
                  onChange={(event) => void onImportFileChange(event)}
                />
                <button
                  type="button"
                  className="btn btn--filled"
                  onClick={() => openImportFilePicker()}
                >
                  ファイルからインポート
                </button>
              </>
            )}
          </div>
        </>
      )}

      {canEdit && (
        <>
          <h2>追加</h2>
          {/* スコアルール・イベント種別ガイドと同じく、見出しの下にフォームを常に出す。 */}
          <form className="alert-rules-add-form" onSubmit={handleAdd}>
            <div className="form-grid alert-rules-form">
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

            <button type="submit" className="btn btn--filled">
              追加
            </button>
          </form>
        </>
      )}

      <h2>一覧</h2>
      {rules.length > 0 && (
        <p className="hint settings-list__hint">
          {canEdit
            ? '行をクリックすると展開され、内容の編集・保存・削除を行えます。'
            : '行をクリックすると展開され、内容を確認できます。'}
        </p>
      )}
      <datalist id="alert-metric-key-options">
        {metricKeyOptions.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>
      {rules.length === 0 ? (
        <p className="hint">ルールが設定されていません。</p>
      ) : (
        <ul className="settings-list alert-rules-list">
          {rules.map((r) => {
            const draft = drafts[r.id] ?? makeDraftFromRule(r)
            const changed = isDraftChanged(r, draft)
            const level = r.alert_level as AlertLevel
            const typeLabel = r.rule_type === 'event_score' ? 'イベントスコア' : 'メトリクス閾値'
            const condition =
              r.rule_type === 'event_score'
                ? `スコア ${r.config.threshold} 以上`
                : `${r.config.metric_key} ≥ ${r.config.threshold}`
            return (
              <SettingsListRow
                key={r.id}
                title={r.name}
                badges={
                  <>
                    <span className={ALERT_LEVEL_BADGE_CLASS[level]}>{ALERT_LEVEL_LABELS[level]}</span>
                    <span className="settings-row__badge">{typeLabel}</span>
                    {r.is_enabled ? null : <span className="settings-row__badge">無効</span>}
                  </>
                }
                preview={condition}
                ariaLabel={`${r.name}、${ALERT_LEVEL_LABELS[level]}、${typeLabel}、${r.is_enabled ? '有効' : '無効'}`}
              >
                <div className="settings-row__fields">
                  <label>
                    ルール名
                    <input
                      type="text"
                      value={draft.name}
                      readOnly={!canEdit}
                      onChange={(e) => updateDraft(r.id, { name: e.target.value })}
                      aria-label={`${r.name} のルール名`}
                    />
                  </label>
                  <label>
                    レベル
                    <select
                      value={draft.alert_level}
                      disabled={!canEdit}
                      onChange={(e) => updateDraft(r.id, { alert_level: e.target.value as AlertLevel })}
                      aria-label={`${r.name} のアラートレベル`}
                      title="クリティカル: すぐ対処 / エラー: 対処必須 / 警告: 検討"
                    >
                      <option value="critical">{ALERT_LEVEL_LABELS.critical}</option>
                      <option value="error">{ALERT_LEVEL_LABELS.error}</option>
                      <option value="warning">{ALERT_LEVEL_LABELS.warning}</option>
                    </select>
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={draft.is_enabled}
                      disabled={!canEdit}
                      onChange={(e) => updateDraft(r.id, { is_enabled: e.target.checked })}
                      aria-label={`${r.name} を有効にする`}
                    />
                    有効（判定の対象にする）
                  </label>
                  <label>
                    閾値
                    <input
                      type="number"
                      value={draft.threshold}
                      readOnly={!canEdit}
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
                        readOnly={!canEdit}
                        onChange={(e) => updateDraft(r.id, { metric_key: e.target.value })}
                        aria-label={`${r.name} のメトリクスキー`}
                      />
                    </label>
                  ) : (
                    <label title="同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで">
                      再通知間隔（分）
                      <input
                        type="number"
                        min={1}
                        value={draft.cooldown_minutes}
                        readOnly={!canEdit}
                        onChange={(e) => updateDraft(r.id, { cooldown_minutes: Number(e.target.value) })}
                        aria-label={`${r.name} の再通知間隔（分）。同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで`}
                      />
                    </label>
                  )}
                </div>
                {canEdit && (
                  <>
                    <p className="hint edit-row-hint">
                      ルールのタイプは変更できません。変更する場合は、既存のルールを削除してから作成し直してください。
                    </p>
                    <div className="settings-row__actions">
                      <button
                        type="button"
                        className="btn btn--filled"
                        disabled={!changed}
                        onClick={() => void handleSaveEdit(r)}
                      >
                        保存
                      </button>
                      <button type="button" className="btn btn--danger" onClick={() => void handleDelete(r.id)}>
                        削除
                      </button>
                    </div>
                  </>
                )}
              </SettingsListRow>
            )
          })}
        </ul>
      )}
    </div>
  )
}
