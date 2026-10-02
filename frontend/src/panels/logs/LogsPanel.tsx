import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiGet } from '../../api'
import { SeverityBadge } from '../../components/badges'
import { EVENT_PAGE_SIZES } from '../../events/constants'
import { collectorStatusListSchema } from '../../api/schemas/plugins'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { EMPTY_ZONED_RANGE_PARTS, zonedRangePartsFromUtcIsoEndpoints, zonedRangePartsToCombinedInputs } from '../../datetime/zonedRangeParts'
import { resolveEventApiRange } from '../../datetime/graphRange'
import { correlationHash, readCorrelationRange } from '../../routing/correlationRange'
import { toErrorMessage } from '../../utils/errors'
import { buildLogExportUrl, buildLogListSearchParams, downloadLogCsv, logPageSchema as pageSchema } from './logExport'
import './LogsPanel.css'

const vcentersSchema = z.array(z.object({ id: z.string(), name: z.string() }))

export function LogsPanel({ onError, active = true }: { onError: (message: string | null) => void; active?: boolean }) {
  const { timeZone } = useTimeZone()
  const initial = readCorrelationRange('logs')
  const [vcenter, setVcenter] = useState(initial?.vcenterId ?? '')
  const [range, setRange] = useState(() => initial ? zonedRangePartsFromUtcIsoEndpoints(initial.from, initial.to, timeZone) : EMPTY_ZONED_RANGE_PARTS)
  const [linkedRange, setLinkedRange] = useState(initial)
  const [source, setSource] = useState('')
  const [kind, setKind] = useState('')
  const [severity, setSeverity] = useState('')
  const [message, setMessage] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<(typeof EVENT_PAGE_SIZES)[number]>(50)
  const [data, setData] = useState<z.infer<typeof pageSchema>>({ items: [], total: 0 })
  const [vcenters, setVcenters] = useState<z.infer<typeof vcentersSchema>>([])
  const [problems, setProblems] = useState<string[]>([])
  const [collectorStatusError, setCollectorStatusError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloadStarted, setDownloadStarted] = useState(false)
  const inputs = zonedRangePartsToCombinedInputs(range)
  const resolvedRange = resolveEventApiRange(inputs.rangeFromInput, inputs.rangeToInput, timeZone)
  const eventRange = resolvedRange.ok ? { vcenterId: vcenter, from: linkedRange?.from ?? resolvedRange.from, to: linkedRange?.to ?? resolvedRange.to } : null

  const rangeSummary = resolvedRange.ok
    ? `${eventRange?.from ? formatIsoInTimeZone(eventRange.from, timeZone) : '開始指定なし'} ～ ${eventRange?.to ? formatIsoInTimeZone(eventRange.to, timeZone) : '終了指定なし'}（${timeZone}）`
    : `期間: ${inputs.rangeFromInput || '開始指定なし'} ～ ${inputs.rangeToInput || '終了指定なし'}（入力を確認）`
  const filterSummary = [
    ['接続先ID', source], ['種別', kind], ['重大度', severity], ['本文', message],
  ].filter(([, value]) => value.trim()).map(([label, value]) => {
    const text = value.trim()
    return `${label}「${text.length > 18 ? `${text.slice(0, 17)}…` : text}」`
  }).join(' · ')

  useEffect(() => {
    const sync = () => {
      const next = readCorrelationRange('logs')
      if (!next) return
      setVcenter(next.vcenterId)
      setLinkedRange(next)
      setRange(zonedRangePartsFromUtcIsoEndpoints(next.from, next.to, timeZone))
      setSource(''); setKind(''); setSeverity(''); setMessage(''); setPage(0)
    }
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [timeZone])

  useEffect(() => {
    let cancelled = false
    apiGet<unknown>('/api/vcenters').then((raw) => {
      if (!cancelled) setVcenters(vcentersSchema.parse(raw))
    }).catch((e) => { if (!cancelled) onError(toErrorMessage(e)) })
    return () => { cancelled = true }
  }, [onError])

  const getFilters = useCallback(() => {
    const inputs = zonedRangePartsToCombinedInputs(range)
    const resolved = resolveEventApiRange(inputs.rangeFromInput, inputs.rangeToInput, timeZone)
    if (!resolved.ok) { onError(resolved.message); return }
    const from = linkedRange?.from ?? resolved.from
    const to = linkedRange?.to ?? resolved.to
    return { vcenter_id: vcenter, source_id: source, log_kind: kind, severity, message_contains: message, from, to }
  }, [range, timeZone, linkedRange, vcenter, source, kind, severity, message, onError])

  const downloadCsv = () => {
    if (loading || data.total === 0) return
    const filters = getFilters()
    if (!filters) return
    onError(null)
    setDownloadStarted(false)
    try {
      downloadLogCsv(buildLogExportUrl(filters, timeZone))
      setDownloadStarted(true)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  useEffect(() => {
    if (!active) return
    let cancelled = false
    let inFlight = false
    const refresh = async () => {
      if (cancelled || inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      try {
        const raw = await apiGet<unknown>('/api/plugins/collectors')
        if (cancelled) return
        const collectors = collectorStatusListSchema.parse(raw).collectors.filter((c) => c.data_kinds.includes('log') || c.id === 'vea.remote.logs')
        setProblems(collectors.flatMap((c) => [
          ...(c.status === 'failed' ? [`${c.display_name ?? c.id}: ${c.error ?? '収集設定エラー'}`] : []),
          ...(c.status === 'disabled' ? [`${c.display_name ?? c.id}: 収集は無効です`] : []),
          ...c.runs.filter((r) => r.status === 'failed' && (!vcenter || r.vcenter_id === vcenter)).map((r) => `${r.vcenter_name}: ${r.error ?? '収集失敗'}`),
        ]))
        setCollectorStatusError(null)
      } catch (e) {
        if (!cancelled) setCollectorStatusError(`収集状況を更新できません: ${toErrorMessage(e)}`)
      } finally {
        inFlight = false
      }
    }
    void refresh()
    const interval = window.setInterval(() => void refresh(), 30_000)
    const onFocus = () => void refresh()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      cancelled = true
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [vcenter, active])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const filters = getFilters()
      if (!filters || cancelled) return
      const params = buildLogListSearchParams(filters, pageSize, page * pageSize)
      setLoading(true); onError(null)
      try {
        const raw = await apiGet<unknown>(`/api/logs?${params}`)
        if (cancelled) return
        const next = pageSchema.parse(raw)
        setData(next)
        if (page > 0 && page * pageSize >= next.total) setPage(Math.max(0, Math.ceil(next.total / pageSize) - 1))

      } catch (e) {
        if (!cancelled) onError(toErrorMessage(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [getFilters, onError, page, pageSize])

  return <div className="panel logs-panel">
    <div className="toolbar" aria-label="ログの操作">
      <label>vCenter<select value={vcenter} onChange={(e) => { setVcenter(e.target.value); setPage(0) }}><option value="">全て</option>{vcenters.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
      <label>
        表示件数
        <select value={pageSize} onChange={(e) => {
          setPageSize(Number(e.target.value) as (typeof EVENT_PAGE_SIZES)[number])
          setPage(0)
        }}>
          {EVENT_PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <div className="toolbar__pagination">
        <button type="button" className="btn" disabled={page === 0 || loading} onClick={() => setPage(page - 1)}>前へ</button>
        <button type="button" className="btn" disabled={(page + 1) * pageSize >= data.total || loading} onClick={() => setPage(page + 1)}>次へ</button>
      </div>
      <span className="toolbar__meta" role="status">
        {loading ? '読み込み中…' : data.total === 0 ? '全 0 件' : `全 ${data.total} 件中 ${page * pageSize + 1}–${Math.min((page + 1) * pageSize, data.total)} 件を表示`}
      </span>
      <button type="button" className="btn btn--gray" disabled={loading || !resolvedRange.ok || data.total === 0} onClick={downloadCsv}>
        CSVをダウンロード
      </button>
      {downloadStarted && <span role="status" className="toolbar__meta">ダウンロードを開始しました。進捗・完了はブラウザで確認してください。</span>}
      {eventRange?.vcenterId && eventRange.from && eventRange.to && <a className="btn btn--gray logs-panel__event-link" href={correlationHash('events', { vcenterId: eventRange.vcenterId, from: eventRange.from, to: eventRange.to })}>同じ期間のイベント</a>}
      <details className="toolbar__filters-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">絞り込み条件</span>
          <span className="toolbar__filters-summary__preview" title={`${rangeSummary} · ${filterSummary || '条件なし'}`}>
            {rangeSummary} · {filterSummary || '条件なし'}
          </span>
        </summary>
        <p className="hint toolbar__filters-hint">表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。未入力の端は制限なし。日付だけ選んだ場合は、開始は 0:00・終了は 23:59 として扱います。</p>
        <p className="hint">CSVの時刻は表示タイムゾーンの日時です。タイムゾーンとUTCオフセットは別列に出力します。途中で失敗した場合は再ダウンロードしてください。</p>
        <p className="hint">発生時刻が未解析のログは取得時刻で検索します。継続行は次のレコード到着後に確定します。</p>
        <p className="hint">指定期間に保存済みのログを検索します。期間を広げても、サーバーの過去ログを追加取得することはありません。初回収集は現行ファイルの末尾1MiBが対象です。</p>
        <ZonedRangeFields value={range} onChange={(next) => { setRange(next); setLinkedRange(null); setPage(0) }} />
        <div className="toolbar__filters" aria-label="ログの絞り込み">
          <label>接続先ID<input value={source} onChange={(e) => { setSource(e.target.value); setPage(0) }} /></label>
          <label>ログ種別<select value={kind} onChange={(e) => { setKind(e.target.value); setPage(0) }}><option value="">全て</option>{['vmkernel', 'hostd', 'vpxa', 'vpxd'].map((k) => <option key={k}>{k}</option>)}</select></label>
          <label>重大度<select value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0) }}><option value="">全て</option>{['panic', 'critical', 'error', 'warning', 'info', 'debug', 'verbose'].map((k) => <option key={k}>{k}</option>)}</select></label>
          <label>本文（含む）<input value={message} onChange={(e) => { setMessage(e.target.value); setPage(0) }} /></label>
        </div>
      </details>
    </div>
    {(problems.length > 0 || collectorStatusError) && <aside className="logs-panel__collection-status" aria-label="ログ収集状況">
      <p className="hint">収集状況に問題があります。保存済みログの検索は引き続き利用できます。収集失敗の詳細は「設定 → プラグイン」と本体の起動ターミナルで確認してください。</p>
      {collectorStatusError && <p role="status" className="error-banner">{collectorStatusError}</p>}
      {problems.map((problem) => <p role="status" className="error-banner" key={problem}>{problem}</p>)}
    </aside>}
    {data.items.length === 0 ? <p className="table-empty">条件に一致するログはありません</p> : <div className="logs-panel__table-scroll"><table className="table"><thead><tr><th>時刻</th><th>接続先</th><th>種別</th><th>重大度</th><th>本文</th></tr></thead><tbody>
      {data.items.map((r) => <tr key={r.id}>
        <td>{formatIsoInTimeZone(r.effective_at, timeZone)}{!r.occurred_at && <small>発生時刻未解析（取得時刻）</small>}</td>
        <td>{r.host}<small>{r.source_id}</small></td><td>{r.log_kind}</td><td><SeverityBadge severity={r.severity} /></td>
        <td><details><summary>{r.message.split('\n')[0].slice(0, 160)}</summary><pre>{r.message}</pre><small>世代: {r.file_generation} / バイト位置: {r.byte_offset}</small><p><a href={correlationHash('events', { vcenterId: r.vcenter_id, from: new Date(Date.parse(r.effective_at) - 300_000).toISOString(), to: new Date(Date.parse(r.effective_at) + 300_000).toISOString() })}>前後5分のイベント</a></p></details></td>
      </tr>)}
    </tbody></table></div>}
  </div>
}
