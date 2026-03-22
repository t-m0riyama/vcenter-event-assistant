import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiGet } from '../../api'
import {
  parseSummary,
  type EventRow,
  type Summary,
  type SummaryHostMetricRow,
} from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { useAutoRefreshPreferences } from '../../preferences/useAutoRefreshPreferences'
import { useSummaryTopNotableMinScore } from '../../preferences/useSummaryTopNotableMinScore'
import { useIntervalWhenEnabled } from '../../hooks/useIntervalWhenEnabled'
import { asArray } from '../../utils/asArray'
import { toErrorMessage } from '../../utils/errors'

export function SummaryPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const { topNotableMinScore } = useSummaryTopNotableMinScore()
  const { autoRefreshEnabled, autoRefreshIntervalMinutes } = useAutoRefreshPreferences()
  const [data, setData] = useState<Summary | null>(null)
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  const load = useCallback(
    async (opts?: { silent?: boolean }) => {
      const silent = opts?.silent === true
      onError(null)
      if (!silent) {
        setLoadState('loading')
      }
      try {
        const q = new URLSearchParams({
          top_notable_min_score: String(topNotableMinScore),
        })
        const raw = await apiGet<unknown>(`/api/dashboard/summary?${q.toString()}`)
        setData(parseSummary(raw))
        setLoadState('ready')
      } catch (e) {
        if (!silent) {
          setData(null)
          setLoadState('error')
        }
        onError(toErrorMessage(e))
      }
    },
    [onError, topNotableMinScore],
  )

  const intervalMs = useMemo(
    () => autoRefreshIntervalMinutes * 60_000,
    [autoRefreshIntervalMinutes],
  )

  const onAutoRefresh = useCallback(() => {
    void load({ silent: true })
  }, [load])

  useIntervalWhenEnabled(autoRefreshEnabled, intervalMs, onAutoRefresh)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  if (loadState === 'loading') return <p>読み込み中…</p>
  if (loadState === 'error' || !data) {
    return <p className="hint">概要を読み込めませんでした。上部のメッセージを確認してください。</p>
  }

  const notableRows = asArray<EventRow>(data.top_notable_events)
  const topEventTypesRows = asArray<Summary['top_event_types_24h'][number]>(
    data.top_event_types_24h,
  )
  const highCpuRows = asArray<SummaryHostMetricRow>(data.high_cpu_hosts)
  const highMemRows = asArray<SummaryHostMetricRow>(data.high_mem_hosts)

  return (
    <div className="panel">
      <div className="stats">
        <div className="stat">
          <span className="label">登録 vCenter</span>
          <span className="num">{data.vcenter_count}</span>
        </div>
        <div className="stat">
          <span className="label">24h イベント</span>
          <span className="num">{data.events_last_24h}</span>
        </div>
        <div className="stat">
          <span className="label">24h 要注意（スコア≥40）</span>
          <span className="num">{data.notable_events_last_24h}</span>
        </div>
      </div>

      <details open className="toolbar__filters-details summary-panel__notable-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">要注意イベント（上位）</span>
          <span className="toolbar__filters-summary__preview">
            {notableRows.length === 0 ? '該当なし' : `${notableRows.length} 件`}
          </span>
        </summary>
        <table className="table">
          <thead>
            <tr>
              <th>時刻</th>
              <th>種別</th>
              <th>スコア</th>
              <th>メッセージ</th>
              <th>運用メモ</th>
            </tr>
          </thead>
          <tbody>
            {notableRows.map((e) => (
              <tr key={e.id}>
                <td>{formatIsoInTimeZone(e.occurred_at, timeZone)}</td>
                <td>{e.event_type}</td>
                <td>{e.notable_score}</td>
                <td className="msg">{e.message}</td>
                <td className="event-comment-cell event-comment-cell--readonly">
                  {e.user_comment ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details className="toolbar__filters-details summary-panel__event-type-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">イベント種別（直近24h 件数上位）</span>
          <span className="toolbar__filters-summary__preview">
            {topEventTypesRows.length === 0 ? '該当なし' : `${topEventTypesRows.length} 件`}
          </span>
        </summary>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">順位</th>
              <th scope="col">種別</th>
              <th scope="col">件数</th>
              <th scope="col">スコア</th>
            </tr>
          </thead>
          <tbody>
            {topEventTypesRows.map((row, i) => (
              <tr key={`${row.event_type}-${i}`}>
                <td>{i + 1}</td>
                <td className="msg">{row.event_type}</td>
                <td>{row.event_count}</td>
                <td>{row.max_notable_score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details open className="toolbar__filters-details summary-panel__host-metric-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">高 CPU ホスト（直近24h サンプル上位）</span>
          <span className="toolbar__filters-summary__preview">
            {highCpuRows.length === 0 ? '該当なし' : `${highCpuRows.length} 件`}
          </span>
        </summary>
        <table className="table">
          <thead>
            <tr>
              <th>ホスト</th>
              <th>CPU %</th>
              <th>時刻</th>
            </tr>
          </thead>
          <tbody>
            {highCpuRows.map((h, i) => (
              <tr key={`${h.entity_name}-${i}`}>
                <td>{h.entity_name}</td>
                <td>{h.value.toFixed(1)}</td>
                <td>{formatIsoInTimeZone(h.sampled_at, timeZone)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <details open className="toolbar__filters-details summary-panel__host-metric-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">
            高メモリ使用率ホスト（直近24h サンプル上位）
          </span>
          <span className="toolbar__filters-summary__preview">
            {highMemRows.length === 0 ? '該当なし' : `${highMemRows.length} 件`}
          </span>
        </summary>
        <table className="table">
          <thead>
            <tr>
              <th>ホスト</th>
              <th>メモリ %</th>
              <th>時刻</th>
            </tr>
          </thead>
          <tbody>
            {highMemRows.map((h, i) => (
              <tr key={`${h.entity_name}-mem-${i}`}>
                <td>{h.entity_name}</td>
                <td>{h.value.toFixed(1)}</td>
                <td>{formatIsoInTimeZone(h.sampled_at, timeZone)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  )
}
