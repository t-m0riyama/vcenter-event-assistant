import type { LogPattern, LogPatternsResponse } from '../../api/schemas/logPatterns'
import { SeverityBadge } from '../../components/badges'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { logSeverityForRank } from './logSeverity'

export function LogPatternsTable({ data, timeZone, onSelect }: {
  data: LogPatternsResponse
  timeZone: string
  onSelect: (pattern: LogPattern) => void
}) {
  return <>
    {data.truncated && <p className="hint" role="note">全 {data.total} 個の型のうち、行数の多い {data.items.length} 個を表示しています。</p>}
    {data.pending_count > 0 && <p className="hint" role="note">型の計算待ちのログが {data.pending_count} 件あります。</p>}
    {data.items.length === 0 ? <p className="table-empty">条件に一致する集計済みの型はありません</p> : (
      <div className="logs-panel__table-scroll">
        <table className="table logs-panel__patterns-table" aria-label="ログの型ごとの集計">
          <thead><tr>
            <th>型</th><th>ログ種別</th><th>vCenter</th><th>行数</th><th>最初の時刻</th><th>最後の時刻</th><th>最大の重大度</th><th>初めて見た時刻</th>
          </tr></thead>
          <tbody>
            {data.items.map((pattern) => (
              <tr key={JSON.stringify([pattern.vcenter_id, pattern.pattern_key])} onClick={() => onSelect(pattern)}>
                <td><button type="button" className="btn btn--gray" onClick={(event) => {
                  event.stopPropagation()
                  onSelect(pattern)
                }}>{pattern.template}</button></td>
                <td>{pattern.log_kind}</td>
                <td>{pattern.vcenter_name || pattern.vcenter_id}</td>
                <td>{pattern.count}</td>
                <td>{formatIsoInTimeZone(pattern.first_utc, timeZone)}</td>
                <td>{formatIsoInTimeZone(pattern.last_utc, timeZone)}</td>
                <td><SeverityBadge severity={logSeverityForRank(pattern.max_severity_rank)} /></td>
                <td>{formatIsoInTimeZone(pattern.first_seen_at, timeZone)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </>
}
