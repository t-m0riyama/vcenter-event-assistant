import { useEffect, useState, useCallback } from 'react'
import { apiGet, apiPost, apiPatch, apiDelete } from '../../api'
import './AlertRulesPanel.css'

type AlertLevel = 'critical' | 'error' | 'warning'

const ALERT_LEVEL_LABELS: Record<AlertLevel, string> = {
  critical: 'クリティカル',
  error: 'エラー',
  warning: '警告',
}

interface AlertRule {
  id: number
  name: string
  rule_type: 'event_score' | 'metric_threshold'
  is_enabled: boolean
  alert_level: AlertLevel
  config: {
    threshold?: number
    metric_key?: string
    cooldown_minutes?: number
  }
  created_at: string
}

/**
 * アラートルールの一覧・新規作成・レベル変更（PATCH）・有効切替・削除を行う設定パネル。
 */
export function AlertRulesPanel({ onError }: { onError: (msg: string) => void }) {
  const [rules, setRules] = useState<AlertRule[]>([])
  const [loading, setLoading] = useState(true)
  const [isAdding, setIsAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<'event_score' | 'metric_threshold'>('event_score')
  const [newAlertLevel, setNewAlertLevel] = useState<AlertLevel>('warning')
  const [newThreshold, setNewThreshold] = useState(60)
  const [newMetricKey, setNewMetricKey] = useState('cpu.usage.average')

  const fetchRules = useCallback(async () => {
    try {
      const data = await apiGet<AlertRule[]>('/api/alerts/rules')
      setRules(data)
    } catch (e) {
      onError(String(e))
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    fetchRules()
  }, [fetchRules])

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
      onError(String(e))
    }
  }

  const handleLevelChange = async (rule: AlertRule, level: AlertLevel) => {
    if (rule.alert_level === level) return
    try {
      await apiPatch(`/api/alerts/rules/${rule.id}`, { alert_level: level })
      fetchRules()
    } catch (e) {
      onError(String(e))
    }
  }

  const handleToggle = async (rule: AlertRule) => {
    try {
      await apiPatch(`/api/alerts/rules/${rule.id}`, {
        is_enabled: !rule.is_enabled
      })
      fetchRules()
    } catch (e) {
      onError(String(e))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('このアラートルールを削除しますか？')) return
    try {
      await apiDelete(`/api/alerts/rules/${id}`)
      fetchRules()
    } catch (e) {
      onError(String(e))
    }
  }

  if (loading) return <div className="loading">アラートルールを読み込み中…</div>

  return (
    <div className="panel alert-rules-panel">
      <div className="alert-rules-panel-header">
        <h2>アラートルール設定</h2>
        <button type="button" className="btn btn--filled" onClick={() => setIsAdding(true)}>
          新規ルール追加
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
                  value={newMetricKey} 
                  onChange={(e) => setNewMetricKey(e.target.value)}
                  placeholder="cpu.usage.average"
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
            rules.map((r) => (
              <tr key={r.id} className={r.is_enabled ? '' : 'disabled-row'}>
                <td>{r.name}</td>
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
                    />
                  </label>
                </td>
                <td className="actions">
                  <button type="button" className="btn btn--gray" onClick={() => handleDelete(r.id)}>削除</button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
