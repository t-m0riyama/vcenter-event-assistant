import { useEffect, useRef, useState, useCallback } from 'react'
import { apiGet, apiPost, apiDelete } from '../../api'
import { useTimeZone } from '../../datetime/useTimeZone'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useAuth } from '../../auth/useAuth'
import { Pagination } from '../../components/Pagination'
import { EVENT_PAGE_SIZES } from '../../events/constants'
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
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<(typeof EVENT_PAGE_SIZES)[number]>(50)
  const [loading, setLoading] = useState(true)

  // apiGet は取り消せないので、ページを素早く送ったときや定期の再取得と重なったときに、
  // 古い要求の応答が後から届いて新しいページを上書きしないよう、最新の要求の応答だけを使う。
  const latestRequestRef = useRef(0)

  const fetchHistory = useCallback(async () => {
    const request = ++latestRequestRef.current
    try {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String((page - 1) * pageSize) })
      const data = await apiGet<HistoryResponse>(`/api/alerts/history?${params}`)
      if (request !== latestRequestRef.current) return
      setHistory(data.items)
      setTotal(data.total)
    } catch (e) {
      if (request !== latestRequestRef.current) return
      onError(String(e))
    } finally {
      if (request === latestRequestRef.current) setLoading(false)
    }
  }, [onError, page, pageSize])

  // 削除などで最後のページが空になったら、残っている最後のページに戻す。
  const lastPage = Math.max(1, Math.ceil(total / pageSize))
  useEffect(() => {
    if (page > lastPage) setPage(lastPage)
  }, [page, lastPage])

  const pagination = {
    total,
    start: total === 0 ? 0 : (page - 1) * pageSize + 1,
    end: Math.min(page * pageSize, total),
    canPrev: page > 1,
    canNext: page * pageSize < total,
    onPrev: () => setPage((p) => Math.max(1, p - 1)),
    onNext: () => setPage((p) => p + 1),
  }

  // 解消・削除・「一覧を更新」の後の再取得は、この合図を進めて effect から行う。ハンドラが
  // 押した時点の fetchHistory を直接呼ぶと、処理中に別のページへ移ったときに元のページを
  // 取り直し、今のページの表示を上書きしてしまうため。
  const [reloadKey, setReloadKey] = useState(0)
  const reload = useCallback(() => setReloadKey((k) => k + 1), [])

  useEffect(() => {
    fetchHistory()
    const timer = setInterval(fetchHistory, 30000)
    return () => clearInterval(timer)
  }, [fetchHistory, reloadKey])

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
      reload()
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
      reload()
    } catch (e) {
      onError(String(e))
    }
  }

  if (loading && history.length === 0) {
    return <div className="loading">通知履歴を読み込み中…</div>
  }

  return (
    <div className="panel alert-history-panel">
      {/* 表示件数・ページ切り替えと「一覧を更新」を同じ行に置き、縦方向の中心を揃える。 */}
      <div className="toolbar alert-history-toolbar">
        <label>
          表示件数
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value) as (typeof EVENT_PAGE_SIZES)[number])
              setPage(1)
            }}
          >
            {EVENT_PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <Pagination position="top" {...pagination} />
        <button type="button" className="btn btn--gray alert-history-refresh" onClick={reload}>
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
      {total > 0 && <Pagination position="bottom" {...pagination} />}
    </div>
  )
}
