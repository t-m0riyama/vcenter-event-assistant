import { useEffect, useState, useCallback } from 'react'
import { apiGet } from '../../api'
import { useTimeZone } from '../../datetime/useTimeZone'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import './AlertHistoryPanel.css'

interface AlertHistory {
  id: number
  rule_id: number
  rule_name: string | null
  state: string
  context_key: string
  notified_at: string
  channel: string
  success: boolean
  error_message: string | null
}

interface HistoryResponse {
  items: AlertHistory[]
  total: number
}

export function AlertHistoryPanel({ onError }: { onError: (msg: string) => void }) {
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

  if (loading && history.length === 0) {
    return <div className="loading">通知履歴を読み込み中…</div>
  }

  return (
    <div className="panel alert-history-panel">
      <div className="alert-history-panel-header">
        <h2>通知履歴</h2>
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
                <th>状態</th>
                <th>対象</th>
                <th>結果</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id}>
                  <td className="col-time">{formatIsoInTimeZone(h.notified_at, timeZone)}</td>
                  <td className="col-rule">{h.rule_name || `Rule #${h.rule_id}`}</td>
                  <td className="col-state">
                    <span className={`state-badge ${h.state}`}>
                      {h.state === 'firing' ? '発火中' : '回復済み'}
                    </span>
                  </td>
                  <td className="col-context">{h.context_key}</td>
                  <td className="col-status">
                    {h.success ? (
                      <span className="success-tag">成功</span>
                    ) : (
                      <span className="error-tag" title={h.error_message || '不明なエラー'}>
                        失敗
                      </span>
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
