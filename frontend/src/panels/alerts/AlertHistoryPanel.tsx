import { useEffect, useState, useCallback } from 'react'
import { apiGet, apiPost, apiDelete } from '../../api'
import { useTimeZone } from '../../datetime/useTimeZone'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useAuth } from '../../auth/useAuth'
import './AlertHistoryPanel.css'

type AlertLevel = 'critical' | 'error' | 'warning'

const ALERT_LEVEL_LABELS: Record<AlertLevel, string> = {
  critical: 'クリティカル',
  error: 'エラー',
  warning: '警告',
}

function alertStateLabel(state: string): string {
  if (state === 'firing') return '発火中'
  if (state === 'stale') return 'データ古い'
  return '回復済み'
}

interface AlertHistory {
  id: number
  rule_id: number
  rule_name: string | null
  rule_type: string
  alert_level: AlertLevel
  state: string
  context_key: string
  notified_at: string
  channel: string
  success: boolean | null
  error_message: string | null
  delivery_status: 'pending' | 'retrying' | 'succeeded' | 'failed' | 'skipped'
  attempt_count: number | null
  last_attempt_at: string | null
  next_attempt_at: string | null
  can_resolve: boolean
}

interface HistoryResponse {
  items: AlertHistory[]
  total: number
}

/**
 * メール通知の履歴一覧（ルール名・レベル・発火/回復・結果）を表示するパネル。
 */
export function AlertHistoryPanel({ onError }: { onError: (msg: string) => void }) {
  const { hasRole } = useAuth()
  const canResolve = hasRole('operator')
  const canDelete = hasRole('admin')
  const { timeZone } = useTimeZone()
  const [history, setHistory] = useState<AlertHistory[]>([])
  const [loading, setLoading] = useState(true)

  const fetchHistory = useCallback(async () => {
    try {
      const data = await apiGet<HistoryResponse>('/api/alerts/history')
      setHistory(data.items)
    } catch (e) {
      onError(String(e))
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    fetchHistory()
    const timer = setInterval(fetchHistory, 30000)
    return () => clearInterval(timer)
  }, [fetchHistory])

  const handleResolve = async (item: AlertHistory) => {
    const label = item.rule_name || `Rule #${item.rule_id}`
    if (
      !confirm(
        `「${label}」の対象「${item.context_key}」を解消しますか？\n回復通知を登録します。登録済みの発火通知は引き続き配送されます。`,
      )
    ) {
      return
    }
    try {
      await apiPost('/api/alerts/states/resolve', {
        rule_id: item.rule_id,
        context_key: item.context_key,
      })
      await fetchHistory()
    } catch (e) {
      onError(String(e))
    }
  }

  const handleDelete = async (item: AlertHistory) => {
    const queued = item.delivery_status === 'pending' || item.delivery_status === 'retrying'
    const message = queued
      ? 'この通知履歴行を削除しますか？待機中の通知も取り消します。送信開始済みのメールは取り消せません。（発火状態自体は変わりません）'
      : 'この通知履歴行を削除しますか？（発火状態自体は変わりません）'
    if (!confirm(message)) return
    try {
      await apiDelete(`/api/alerts/history/${item.id}`)
      await fetchHistory()
    } catch (e) {
      onError(String(e))
    }
  }

  if (loading && history.length === 0) {
    return <div className="loading">通知履歴を読み込み中…</div>
  }

  return (
    <div className="panel alert-history-panel">
      <div className="alert-history-panel-header">
        <h2>通知履歴</h2>
        <p className="alert-history-note">
          event_score 型はイベント発生を点で検知するため、自動では「回復済み」になりません。解消ボタンで手動 resolve してください。
        </p>
        <p className="alert-history-note">
          日時は配送待ちでは登録時刻、試行後は最新の試行時刻です。失敗した通知は最大24時間（サーバー設定で変更可）再送します。
        </p>
        <button type="button" className="btn btn--gray alert-history-refresh" onClick={() => void fetchHistory()}>
          一覧を更新
        </button>
      </div>

      {history.length === 0 ? (
        <p className="no-data">通知履歴はありません。</p>
      ) : (
        <div className="table-container">
          <table className="alert-history-table">
            <thead>
              <tr>
                <th>日時</th>
                <th>ルール名</th>
                <th>レベル</th>
                <th>状態</th>
                <th>対象</th>
                <th>結果</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td className="col-time">{formatIsoInTimeZone(h.notified_at, timeZone)}</td>
                  <td className="col-rule">{h.rule_name || `Rule #${h.rule_id}`}</td>
                  <td className="col-level">
                    <span className={`level-badge level-badge--${h.alert_level}`}>
                      {ALERT_LEVEL_LABELS[h.alert_level] ?? h.alert_level}
                    </span>
                  </td>
                  <td className="col-state">
                    <span className={`state-badge ${h.state}`}>
                      {alertStateLabel(h.state)}
                    </span>
                  </td>
                  <td className="col-context">{h.context_key}</td>
                  <td className="col-status">
                    {h.delivery_status === 'pending' || h.delivery_status === 'retrying' ? (
                      <span className="skipped-tag" title={h.error_message || undefined}>
                        {h.delivery_status === 'pending' ? '配送待ち' : '再送待ち'}
                      </span>
                    ) : h.delivery_status === 'skipped' ? (
                      <span className="skipped-tag" title={h.error_message || 'SMTP 未設定'}>
                        未送信
                      </span>
                    ) : h.delivery_status === 'succeeded' ? (
                      <span className="success-tag">成功</span>
                    ) : (
                      <span className="error-tag" title={h.error_message || '不明なエラー'}>
                        {h.attempt_count !== null && (h.attempt_count > 0 || h.error_message?.startsWith('retry deadline exceeded')) ? '打ち切り' : '失敗'}
                      </span>
                    )}
                    <div className="delivery-attempts">試行: {h.attempt_count ?? '不明'}回</div>
                    {h.next_attempt_at && (
                      <div className="delivery-next-attempt">次回: {formatIsoInTimeZone(h.next_attempt_at, timeZone)}</div>
                    )}
                  </td>
                  <td className="col-actions">
                    {canResolve && h.can_resolve && (
                      <button
                        type="button"
                        className="btn btn--gray alert-history-action"
                        onClick={() => void handleResolve(h)}
                      >
                        解消
                      </button>
                    )}
                    {canDelete && (
                      <button
                        type="button"
                        className="btn btn--danger alert-history-action"
                        onClick={() => void handleDelete(h)}
                      >
                        削除
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
