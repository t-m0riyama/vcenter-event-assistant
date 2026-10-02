import { useCallback, useEffect, useState } from 'react'
import { z } from 'zod'
import { apiGet } from '../../api'
import { collectorStatusListSchema } from '../../api/schemas/plugins'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { EMPTY_ZONED_RANGE_PARTS, zonedRangePartsFromUtcIsoEndpoints, zonedRangePartsToCombinedInputs } from '../../datetime/zonedRangeParts'
import { resolveEventApiRange } from '../../datetime/graphRange'
import { correlationHash, readCorrelationRange } from '../../routing/correlationRange'
import { toErrorMessage } from '../../utils/errors'
import './LogsPanel.css'

const logSchema = z.object({
  id: z.number(), vcenter_id: z.string(), source_id: z.string(), host: z.string(), log_kind: z.string(),
  file_generation: z.string(), byte_offset: z.number(), occurred_at: z.string().nullable(),
  collected_at: z.string(), effective_at: z.string(), severity: z.string().nullable(), message: z.string(),
})
const pageSchema = z.object({ items: z.array(logSchema), total: z.number().int() })
const vcentersSchema = z.array(z.object({ id: z.string(), name: z.string() }))

export function LogsPanel({ onError }: { onError: (message: string | null) => void }) {
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
  const [data, setData] = useState<z.infer<typeof pageSchema>>({ items: [], total: 0 })
  const [vcenters, setVcenters] = useState<z.infer<typeof vcentersSchema>>([])
  const [problems, setProblems] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const inputs = zonedRangePartsToCombinedInputs(range)
  const resolvedRange = resolveEventApiRange(inputs.rangeFromInput, inputs.rangeToInput, timeZone)
  const eventRange = resolvedRange.ok ? { vcenterId: vcenter, from: linkedRange?.from ?? resolvedRange.from, to: linkedRange?.to ?? resolvedRange.to } : null

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

  const load = useCallback(async () => {
    const inputs = zonedRangePartsToCombinedInputs(range)
    const resolved = resolveEventApiRange(inputs.rangeFromInput, inputs.rangeToInput, timeZone)
    if (!resolved.ok) { onError(resolved.message); return }
    const from = linkedRange?.from ?? resolved.from
    const to = linkedRange?.to ?? resolved.to
    const params = new URLSearchParams({ limit: '50', offset: String(page * 50) })
    for (const [key, value] of Object.entries({ vcenter_id: vcenter, source_id: source, log_kind: kind, severity, message_contains: message, from, to })) {
      if (value) params.set(key, value)
    }
    return { params, vcenter }
  }, [range, timeZone, linkedRange, page, vcenter, source, kind, severity, message, onError])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const request = await load()
      if (!request || cancelled) return
      setLoading(true); onError(null)
      try {
        const [raw, status] = await Promise.all([
          apiGet<unknown>(`/api/logs?${request.params}`), apiGet<unknown>('/api/plugins/collectors'),
        ])
        if (cancelled) return
        const next = pageSchema.parse(raw)
        setData(next)
        if (page > 0 && page * 50 >= next.total) setPage(Math.max(0, Math.ceil(next.total / 50) - 1))
        const collectors = collectorStatusListSchema.parse(status).collectors.filter((c) => c.data_kinds.includes('log') || c.id === 'vea.remote.logs')
        setProblems(collectors.flatMap((c) => [
          ...(c.status === 'failed' ? [`${c.display_name ?? c.id}: ${c.error ?? '収集設定エラー'}`] : []),
          ...(c.status === 'disabled' ? [`${c.display_name ?? c.id}: 収集は無効です`] : []),
          ...c.runs.filter((r) => r.status === 'failed' && (!request.vcenter || r.vcenter_id === request.vcenter)).map((r) => `${r.vcenter_name}: ${r.error ?? '収集失敗'}`),
        ]))
      } catch (e) {
        if (!cancelled) onError(toErrorMessage(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [load, onError, page, refresh])

  return <div className="panel logs-panel">
    <h2>ログ検索</h2>
    <p className="hint">発生時刻が未解析のログは取得時刻で検索します。継続行は次のレコード到着後に確定します。</p>
    <p className="hint">指定期間に保存済みのログを検索します。期間を広げても、サーバーの過去ログを追加取得することはありません。初回収集は現行ファイルの末尾1MiBが対象です。</p>
    {problems.length > 0 && <aside aria-label="ログ収集状況">
      <p>収集状況に問題があります。保存済みログの検索は引き続き利用できます。収集失敗の詳細は「設定 → プラグイン」と本体の起動ターミナルで確認してください。</p>
      {problems.map((problem) => <p role="status" className="error-banner" key={problem}>{problem}</p>)}
    </aside>}
    <div className="toolbar" aria-label="ログの絞り込み">
      <label>vCenter<select value={vcenter} onChange={(e) => { setVcenter(e.target.value); setPage(0) }}><option value="">全て</option>{vcenters.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
      <label>接続先ID<input value={source} onChange={(e) => { setSource(e.target.value); setPage(0) }} /></label>
      <label>ログ種別<select value={kind} onChange={(e) => { setKind(e.target.value); setPage(0) }}><option value="">全て</option>{['vmkernel', 'hostd', 'vpxa', 'vpxd'].map((k) => <option key={k}>{k}</option>)}</select></label>
      <label>重大度<select value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0) }}><option value="">全て</option>{['panic', 'critical', 'error', 'warning', 'info', 'debug', 'verbose'].map((k) => <option key={k}>{k}</option>)}</select></label>
      <label>本文（含む）<input value={message} onChange={(e) => { setMessage(e.target.value); setPage(0) }} /></label>
    </div>
    <ZonedRangeFields value={range} onChange={(next) => { setRange(next); setLinkedRange(null); setPage(0) }} />
    <div className="toolbar">
      <button className="btn" disabled={page === 0 || loading} onClick={() => setPage(page - 1)}>前へ</button>
      <button className="btn" disabled={(page + 1) * 50 >= data.total || loading} onClick={() => setPage(page + 1)}>次へ</button>
      <span>{loading ? '読み込み中…' : `全 ${data.total} 件 / ${page + 1} ページ`}</span>
      <button className="btn" disabled={loading} onClick={() => setRefresh((n) => n + 1)}>更新</button>
      {eventRange?.vcenterId && eventRange.from && eventRange.to && <a className="btn" href={correlationHash('events', { vcenterId: eventRange.vcenterId, from: eventRange.from, to: eventRange.to })}>同じ期間のイベント</a>}
    </div>
    {data.items.length === 0 ? <p className="table-empty">条件に一致するログはありません</p> : <table className="table"><thead><tr><th>時刻</th><th>接続先</th><th>種別</th><th>重大度</th><th>本文</th></tr></thead><tbody>
      {data.items.map((r) => <tr key={r.id}>
        <td>{formatIsoInTimeZone(r.effective_at, timeZone)}{!r.occurred_at && <small>発生時刻未解析（取得時刻）</small>}</td>
        <td>{r.host}<small>{r.source_id}</small></td><td>{r.log_kind}</td><td>{r.severity ?? '—'}</td>
        <td><details><summary>{r.message.split('\n')[0].slice(0, 160)}</summary><pre>{r.message}</pre><small>世代: {r.file_generation} / バイト位置: {r.byte_offset}</small><p><a href={correlationHash('events', { vcenterId: r.vcenter_id, from: new Date(Date.parse(r.effective_at) - 300_000).toISOString(), to: new Date(Date.parse(r.effective_at) + 300_000).toISOString() })}>前後5分のイベント</a></p></details></td>
      </tr>)}
    </tbody></table>}
  </div>
}
