import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiGet, apiPost, apiPatch, apiDelete } from '../../api'
import {
  alertRuleRowSchema,
  alertRulesFileSchema,
  alertRulesImportResponseSchema,
  buildAlertRulesExportPayload,
  type AlertRuleRow,
} from '../../api/schemas'
import { eventPatternsResponseSchema, type EventPattern } from '../../api/schemas/eventPatterns'
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
import {
  applyAlertRuleEdit,
  discardAlertRuleDraft,
  draftKey,
  draftValues,
  markAlertRuleDraftConflict,
  reconcileAlertRuleDrafts,
  samePatternIds,
  type AlertLevel,
  type AlertRuleDrafts,
  type AlertRuleDraftSource,
  type EditDraft,
} from './alertRuleDrafts'

const ALERT_LEVEL_LABELS: Record<AlertLevel, string> = {
  critical: 'クリティカル',
  error: 'エラー',
  warning: '警告',
}

type AlertRule = AlertRuleRow & Pick<AlertRuleDraftSource, 'config'>
type AlertRuleType = AlertRule['rule_type']

const RULE_TYPE_LABELS: Record<AlertRuleType, string> = {
  event_score: 'イベントスコア',
  metric_threshold: 'メトリクス閾値',
  event_pattern: '障害パターン',
}

function PatternSelection({ catalog, selected, ruleName, disabled, onChange }: {
  catalog: ReadonlyMap<string, string>
  selected: readonly string[]
  ruleName?: string
  disabled?: boolean
  onChange: (ids: string[]) => void
}) {
  const options = new Set([...catalog.keys(), ...selected])
  return (
    <fieldset className="alert-rule-patterns" disabled={disabled}>
      <legend>{ruleName ? `${ruleName} の対象のパターン` : '対象のパターン'}</legend>
      <p className="hint">選択なしの場合は、今後追加されるものも含めてすべてのパターンを判定します。</p>
      {[...options].map((id) => (
        <label key={id} className="check">
          <input
            type="checkbox"
            checked={selected.includes(id)}
            onChange={(e) => onChange(e.target.checked ? [...selected, id] : selected.filter((value) => value !== id))}
          />
          {catalog.get(id) ?? id}
        </label>
      ))}
    </fieldset>
  )
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

  const { list: rules, updateList, loading, load: fetchRules } = useSettingsListFetch({
    onError,
    fetchList,
  })

  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<AlertRuleType>('event_score')
  const [newAlertLevel, setNewAlertLevel] = useState<AlertLevel>('warning')
  const [newThreshold, setNewThreshold] = useState(60)
  const [newPatternIds, setNewPatternIds] = useState<string[]>([])
  const [newCooldown, setNewCooldown] = useState(10)
  const [patterns, setPatterns] = useState<EventPattern[]>([])
  const [patternLoadFailed, setPatternLoadFailed] = useState(false)
  const needsPatterns = newType === 'event_pattern' || rules.some((rule) => rule.rule_type === 'event_pattern')
  const patternTitles = new Map(patterns.map(({ id, title }) => [id, title]))
  const [newMetricKey, setNewMetricKey] = useState<string>(DEFAULT_ALERT_METRIC_KEY)
  /** 行ごとの編集中の値（持ち方と、読み直したときの比べ方は `alertRuleDrafts.ts`）。 */
  const [drafts, setDrafts] = useState<AlertRuleDrafts>({})
  const [busyRows, setBusyRows] = useState<ReadonlySet<string>>(() => new Set())
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

  useEffect(() => {
    if (!needsPatterns) return
    let active = true
    void apiGet<unknown>('/api/event-patterns')
      .then((data) => {
        const catalog = eventPatternsResponseSchema.parse(data)
        if (active) {
          setPatterns(catalog)
          setPatternLoadFailed(false)
        }
      })
      .catch(() => {
        if (active) setPatternLoadFailed(true)
      })
    return () => { active = false }
  }, [needsPatterns])

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
      let config: AlertRuleDraftSource['config']
      switch (newType) {
        case 'event_score':
          config = { threshold: newThreshold, cooldown_minutes: 10 }
          break
        case 'metric_threshold':
          config = { metric_key: newMetricKey, threshold: newThreshold }
          break
        case 'event_pattern':
          config = { pattern_ids: newPatternIds, cooldown_minutes: newCooldown }
          break
      }

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

  const handleDelete = async (rule: AlertRule) => {
    if (!confirm('このアラートルールを削除しますか？通知履歴と待機中の通知も削除されます。送信開始済みのメールは取り消せません。')) return
    try {
      await apiDelete(`/api/alerts/rules/${rule.id}`)
      discardDraft(rule)
      fetchRules()
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const updateDraft = (rule: AlertRule, patch: Partial<EditDraft>) => {
    setDrafts((prev) => applyAlertRuleEdit(prev, rule, patch))
  }

  const discardDraft = (rule: AlertRule) => {
    setDrafts((prev) => discardAlertRuleDraft(prev, rule))
  }

  const setRuleBusy = (key: string, busy: boolean) => {
    setBusyRows((prev) => {
      const next = new Set(prev)
      if (busy) next.add(key)
      else next.delete(key)
      return next
    })
  }

  // 一覧を読み直すたびに下書きと比べ直す（消えたルールの下書きを捨て、競合に印を付ける）。
  useEffect(() => {
    setDrafts((prev) => reconcileAlertRuleDrafts(prev, rules))
  }, [rules])

  /** 読み直せたときに、競合した行の下書きを捨てる。 */
  const handleDiscardConflict = async (rule: AlertRule) => {
    const key = draftKey(rule)
    if (busyRows.has(key)) return
    setRuleBusy(key, true)
    try {
      await fetchRules(() => discardDraft(rule))
    } finally {
      setRuleBusy(key, false)
    }
  }

  const isDraftChanged = (rule: AlertRule, draft: EditDraft): boolean => {
    if (draft.name.trim() !== rule.name) return true
    if (draft.alert_level !== rule.alert_level) return true
    if (draft.is_enabled !== rule.is_enabled) return true
    if (rule.rule_type === 'event_pattern' && !samePatternIds(rule.config.pattern_ids ?? [], draft.pattern_ids)) return true
    if (rule.rule_type !== 'event_pattern' && Number(rule.config.threshold ?? 0) !== draft.threshold) return true
    if (rule.rule_type === 'metric_threshold') return (rule.config.metric_key ?? '') !== draft.metric_key
    return Number(rule.config.cooldown_minutes ?? 10) !== draft.cooldown_minutes
  }

  const handleSaveEdit = async (rule: AlertRule) => {
    const key = draftKey(rule)
    const entry = drafts[key]
    if (!entry || entry.conflict || entry.baseRevision !== rule.revision || busyRows.has(key)) return
    const edits = entry.edits
    const draft = draftValues(rule, entry)
    const nextName = draft.name.trim()
    if (!nextName) {
      onError('ルール名は必須です。')
      return
    }
    if (rule.rule_type !== 'event_pattern' && !Number.isFinite(draft.threshold)) {
      onError('閾値には数値を入力してください。')
      return
    }

    if (rule.rule_type === 'event_pattern' && edits.cooldown_minutes !== undefined
      && (!Number.isInteger(draft.cooldown_minutes) || draft.cooldown_minutes < 1)) {
      onError('再通知間隔は 1 以上の整数を入力してください。')
      return
    }

    // 変えた項目だけを送る（変えていない項目まで送ると、編集中に読み直した値を古い値で戻してしまう）。
    const body: Record<string, unknown> = { revision: entry.baseRevision }
    if (edits.name !== undefined) body.name = nextName
    if (edits.alert_level !== undefined) body.alert_level = edits.alert_level
    if (edits.is_enabled !== undefined) body.is_enabled = edits.is_enabled
    const nextConfig: AlertRule['config'] = { ...rule.config }
    let configEdited = false
    if (edits.threshold !== undefined) {
      nextConfig.threshold = edits.threshold
      configEdited = true
    }
    if (rule.rule_type === 'metric_threshold' && edits.metric_key !== undefined) {
      nextConfig.metric_key = edits.metric_key.trim()
      configEdited = true
    }
    if (rule.rule_type !== 'metric_threshold' && edits.cooldown_minutes !== undefined) {
      nextConfig.cooldown_minutes = edits.cooldown_minutes
      configEdited = true
    }
    if (rule.rule_type === 'event_pattern' && edits.pattern_ids !== undefined) {
      nextConfig.pattern_ids = edits.pattern_ids
      configEdited = true
    }
    if (configEdited) body.config = nextConfig

    setRuleBusy(key, true)
    try {
      const response = await apiPatch<unknown>(`/api/alerts/rules/${rule.id}`, body)
      const saved = alertRuleRowSchema.parse(response) as AlertRule
      updateList((rows) => rows.map((row) => (
        row.id === rule.id && row.revision === rule.revision ? saved : row
      )))
      discardDraft(rule)
      await fetchRules()
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || (e.status === 409 && e.errorCode === 'alert_rule_stale'))) {
        setDrafts((prev) => markAlertRuleDraftConflict(prev, rule))
      } else {
        onError(toErrorMessage(e))
      }
    } finally {
      setRuleBusy(key, false)
    }
  }

  if (loading) return <div className="loading">アラートルールを読み込み中…</div>

  return (
    <div className="panel alert-rules-panel">
      <p className="hint">
        イベントのスコア・メトリクス・障害パターンに基づくアラートの判定ルールをサーバーに保存します。判定の対象となるのは、有効にしたルールのみです。
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
                <select value={newType} onChange={(e) => setNewType(e.target.value as AlertRuleType)}>
                  {Object.entries(RULE_TYPE_LABELS).map(([type, label]) => (
                    <option key={type} value={type}>{label}</option>
                  ))}
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

              {newType === 'event_pattern' ? (
                <>
                  <label>
                    再通知間隔（分）
                    <input
                      type="number"
                      min={1}
                      value={newCooldown}
                      onChange={(e) => setNewCooldown(Number(e.target.value))}
                      required
                    />
                  </label>
                  <PatternSelection catalog={patternTitles} selected={newPatternIds} onChange={setNewPatternIds} />
                </>
              ) : (
                <label>
                  閾値
                  <input
                    type="number"
                    value={newThreshold}
                    onChange={(e) => setNewThreshold(Number(e.target.value))}
                    required
                  />
                </label>
              )}
            </div>

            <button type="submit" className="btn btn--filled">
              追加
            </button>
          </form>
        </>
      )}

      {needsPatterns && patternLoadFailed && <p className="hint" role="status">障害パターンの一覧を取得できませんでした。</p>}

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
            const key = draftKey(r)
            const entry = drafts[key]
            const draft = draftValues(r, entry)
            const conflict = entry?.conflict ?? false
            const busy = busyRows.has(key)
            const editable = canEdit && !busy
            const changed = isDraftChanged(r, draft)
            const level = r.alert_level as AlertLevel
            const typeLabel = RULE_TYPE_LABELS[r.rule_type]
            let condition: string
            switch (r.rule_type) {
              case 'event_score':
                condition = `スコア ${r.config.threshold} 以上`
                break
              case 'metric_threshold':
                condition = `${r.config.metric_key} ≥ ${r.config.threshold}`
                break
              case 'event_pattern':
                condition = r.config.pattern_ids?.map((id) => patternTitles.get(id) ?? id).join('、') || 'すべてのパターン'
                break
            }
            return (
              <SettingsListRow
                key={r.id}
                title={r.name}
                badges={
                  <>
                    <span className={ALERT_LEVEL_BADGE_CLASS[level]}>{ALERT_LEVEL_LABELS[level]}</span>
                    <span className="settings-row__badge">{typeLabel}</span>
                    {r.is_enabled ? null : <span className="settings-row__badge">無効</span>}
                    {conflict ? (
                      <span className="settings-row__badge settings-row__badge--caution">ほかの操作で変更あり</span>
                    ) : null}
                  </>
                }
                preview={condition}
                ariaLabel={`${r.name}、${ALERT_LEVEL_LABELS[level]}、${typeLabel}、${r.is_enabled ? '有効' : '無効'}${conflict ? '、ほかの操作で変更あり' : ''}`}
              >
                <div className="settings-row__fields">
                  <label>
                    ルール名
                    <input
                      type="text"
                      value={draft.name}
                      readOnly={!editable}
                      onChange={(e) => updateDraft(r, { name: e.target.value })}
                      aria-label={`${r.name} のルール名`}
                    />
                  </label>
                  <label>
                    レベル
                    <select
                      value={draft.alert_level}
                      disabled={!editable}
                      onChange={(e) => updateDraft(r, { alert_level: e.target.value as AlertLevel })}
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
                      disabled={!editable}
                      onChange={(e) => updateDraft(r, { is_enabled: e.target.checked })}
                      aria-label={`${r.name} を有効にする`}
                    />
                    有効（判定の対象にする）
                  </label>
                  {r.rule_type !== 'event_pattern' && (
                    <label>
                      閾値
                      <input
                        type="number"
                        value={draft.threshold}
                        readOnly={!editable}
                        onChange={(e) => updateDraft(r, { threshold: Number(e.target.value) })}
                        aria-label={`${r.name} の閾値`}
                      />
                    </label>
                  )}
                  {r.rule_type === 'metric_threshold' ? (
                    <label>
                      メトリクスキー
                      <input
                        type="text"
                        list="alert-metric-key-options"
                        value={draft.metric_key}
                        readOnly={!editable}
                        onChange={(e) => updateDraft(r, { metric_key: e.target.value })}
                        aria-label={`${r.name} のメトリクスキー`}
                      />
                    </label>
                  ) : (
                    <label title={r.rule_type === 'event_pattern' ? '同じパターン・対象で再通知するまでの間隔' : '同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで'}>
                      再通知間隔（分）
                      <input
                        type="number"
                        min={1}
                        value={draft.cooldown_minutes}
                        readOnly={!editable}
                        onChange={(e) => updateDraft(r, { cooldown_minutes: Number(e.target.value) })}
                        aria-label={r.rule_type === 'event_score'
                          ? `${r.name} の再通知間隔（分）。同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで`
                          : `${r.name} の再通知間隔（分）`}
                      />
                    </label>
                  )}
                  {r.rule_type === 'event_pattern' && (
                    <PatternSelection
                      catalog={patternTitles}
                      selected={draft.pattern_ids}
                      ruleName={r.name}
                      disabled={!editable}
                      onChange={(pattern_ids) => updateDraft(r, { pattern_ids })}
                    />
                  )}
                </div>
                {canEdit && (
                  <>
                    <p className="hint edit-row-hint">
                      ルールのタイプは変更できません。変更する場合は、既存のルールを削除してから作成し直してください。
                    </p>
                    {conflict && (
                      <p className="hint alert-rules-conflict" role="alert">
                        編集中に、このルールがサーバー上で変更または削除されました。上書きを防ぐため保存できません。「編集を破棄して読み直す」を押して最新の内容を確認してください。
                      </p>
                    )}
                    <div className="settings-row__actions">
                      {conflict && (
                        <button type="button" className="btn btn--gray" disabled={busy} onClick={() => void handleDiscardConflict(r)}>
                          編集を破棄して読み直す
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn--filled"
                        disabled={!changed || conflict || busy || entry?.baseRevision !== r.revision}
                        onClick={() => void handleSaveEdit(r)}
                      >
                        保存
                      </button>
                      <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void handleDelete(r)}>
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
