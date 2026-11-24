import { useCallback, useEffect, useMemo, useState } from 'react'
import { z } from 'zod'
import { ApiError, apiGet, formatValidationMessage, prepareBrowserRequest, waitForRetryAfter } from '../../api'
import { SeverityBadge } from '../../components/badges'
import { Pagination } from '../../components/Pagination'
import { EVENT_PAGE_SIZES } from '../../events/constants'
import { logPatternsResponseSchema, type LogPattern, type LogPatternsResponse } from '../../api/schemas/logPatterns'
import { collectorStatusListSchema } from '../../api/schemas/plugins'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { EMPTY_ZONED_RANGE_PARTS, zonedRangePartsFromUtcIsoEndpoints, zonedRangePartsToCombinedInputs } from '../../datetime/zonedRangeParts'
import { resolveEventApiRange } from '../../datetime/graphRange'
import { correlationHash, readCorrelationRange, type CorrelationRange } from '../../routing/correlationRange'
import { toErrorMessage } from '../../utils/errors'
import { LogPatternsTable } from './LogPatternsTable'
import { buildLogExportUrl, buildLogFilterSearchParams, buildLogListSearchParams, downloadLogCsv, logPageSchema as pageSchema } from './logExport'
import './LogsPanel.css'

const vcentersSchema = z.array(z.object({ id: z.string(), name: z.string() }))
const PATTERN_DEBOUNCE_MS = 400

type SelectedPattern = {
  key: string
  vcenterId: string
  template?: string
  lookupPeriod?: Pick<CorrelationRange, 'from' | 'to'>
}
type PatternResult = {
  condition: string
  result: LogPatternsResponse | 'scan-limit' | 'busy' | 'error'
}

function patternFromLink(link: CorrelationRange | null): SelectedPattern | null {
  if (!link?.patternKey) return null
  return { key: link.patternKey, vcenterId: link.vcenterId, lookupPeriod: { from: link.from, to: link.to } }
}

function linkedPatternCondition(pattern: SelectedPattern | null): string | null {
  if (!pattern?.lookupPeriod) return null
  return new URLSearchParams({
    vcenter_id: pattern.vcenterId, pattern_key: pattern.key, ...pattern.lookupPeriod,
  }).toString()
}

async function fetchLogPatterns(condition: string, signal: AbortSignal): Promise<LogPatternsResponse> {
  const call = async () => logPatternsResponseSchema.parse(await apiGet<unknown>(`/api/logs/patterns?${condition}`, signal))
  try {
    return await call()
  } catch (first) {
    if (!(first instanceof ApiError) || first.status !== 503) throw first
    await waitForRetryAfter(first.retryAfterSeconds, signal)
    signal.throwIfAborted()
    return call()
  }
}

function removeLinkedPattern(vcenterId?: string) {
  const url = new URL(window.location.href)
  const [path, query] = url.hash.split('?', 2)
  if (path !== '#/logs') return
  const params = new URLSearchParams(query)
  if (!params.has('pattern_key')) return
  params.delete('pattern_key')
  if (vcenterId !== undefined) {
    if (vcenterId) params.set('vcenter_id', vcenterId)
    else params.delete('vcenter_id')
  }
  url.hash = params.size > 0 ? `${path}?${params}` : path
  window.history.replaceState(window.history.state, '', url)
}

export function LogsPanel({ onError, active = true }: { onError: (message: string | null) => void; active?: boolean }) {
  const { timeZone } = useTimeZone()
  const initial = readCorrelationRange('logs')
  const [view, setView] = useState<'list' | 'patterns'>('list')
  const [selectedPattern, setSelectedPattern] = useState(() => patternFromLink(initial))
  const [patterns, setPatterns] = useState<PatternResult | null>(null)
  const [vcenterSelection, setVcenterSelection] = useState(initial?.vcenterId ?? '')
  const vcenter = selectedPattern?.vcenterId ?? vcenterSelection
  const patternKeyLabel = selectedPattern ? `キー ${selectedPattern.key.slice(0, 8)}…` : ''
  const lookupCondition = linkedPatternCondition(selectedPattern)
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
  const resolvedRange = linkedRange
    ? { ok: true as const, from: linkedRange.from, to: linkedRange.to }
    : resolveEventApiRange(inputs.rangeFromInput, inputs.rangeToInput, timeZone)
  const rangeError = resolvedRange.ok ? null : resolvedRange.message
  const from = resolvedRange.ok ? resolvedRange.from : undefined
  const to = resolvedRange.ok ? resolvedRange.to : undefined

  const rangeSummary = resolvedRange.ok
    ? `${from ? formatIsoInTimeZone(from, timeZone) : '開始指定なし'} ～ ${to ? formatIsoInTimeZone(to, timeZone) : '終了指定なし'}（${timeZone}）`
    : `期間: ${inputs.rangeFromInput || '開始指定なし'} ～ ${inputs.rangeToInput || '終了指定なし'}（入力を確認）`
  const pagination = {
    total: data.total,
    start: page * pageSize + 1,
    end: Math.min((page + 1) * pageSize, data.total),
    canPrev: page > 0,
    canNext: (page + 1) * pageSize < data.total,
    onPrev: () => setPage(page - 1),
    onNext: () => setPage(page + 1),
    loading,
  }
  const filterSummary = [
    ['接続先ID', source], ['種別', kind], ['重大度', severity], ['本文', message],
    ['型', selectedPattern?.template || patternKeyLabel],
  ].filter(([, value]) => value.trim()).map(([label, value]) => {
    const text = value.trim()
    return `${label}「${text.length > 18 ? `${text.slice(0, 17)}…` : text}」`
  }).join(' · ')

  useEffect(() => {
    const sync = () => {
      const next = readCorrelationRange('logs')
      if (!next) return
      setVcenterSelection(next.vcenterId)
      setSelectedPattern(patternFromLink(next))
      setView('list')
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

  const filters = useMemo(() => ({
    vcenter_id: vcenter, source_id: source, log_kind: kind, severity, message_contains: message, from, to,
  }), [vcenter, source, kind, severity, message, from, to])
  const patternKey = selectedPattern?.key
  const getFilters = useCallback(() => {
    if (rangeError) { onError(rangeError); return }
    return { ...filters, pattern_key: patternKey }
  }, [rangeError, filters, patternKey, onError])

  const openPattern = (pattern: LogPattern) => {
    setSelectedPattern({ key: pattern.pattern_key, vcenterId: pattern.vcenter_id, template: pattern.template })
    setPage(0)
    setData({ items: [], total: 0 })
    setView('list')
  }

  const clearPattern = (nextVCenter?: string) => {
    setSelectedPattern(null)
    setPage(0)
    setData({ items: [], total: 0 })
    removeLinkedPattern(nextVCenter)
  }

  useEffect(() => {
    if (!lookupCondition) return
    const request = new AbortController()
    void fetchLogPatterns(lookupCondition, request.signal).then(({ items }) => {
      const template = items[0]?.template
      if (template && !request.signal.aborted) {
        setSelectedPattern((current) => current && linkedPatternCondition(current) === lookupCondition
          ? { ...current, template }
          : current)
      }
    }).catch(() => {
      // 型名を取得できなければ、キーを表示したままログを検索できる。
    })
    return () => request.abort()
  }, [lookupCondition])

  const patternCondition = view === 'patterns' && from && to ? buildLogFilterSearchParams(filters).toString() : null
  const patternResult = patterns?.condition === patternCondition ? patterns.result : null
  useEffect(() => {
    if (view !== 'patterns') return
    setPatterns(null)
    onError(rangeError)
    if (!patternCondition) return

    const request = new AbortController()
    const timer = window.setTimeout(() => {
      void fetchLogPatterns(patternCondition, request.signal).then((result) => {
        if (!request.signal.aborted) setPatterns({ condition: patternCondition, result })
      }).catch((e: unknown) => {
        if (request.signal.aborted) return
        let result: PatternResult['result'] = 'error'
        if (e instanceof ApiError && e.status === 503) {
          result = 'busy'
        } else if (e instanceof ApiError && e.status === 422) {
          if (e.detail && typeof e.detail === 'object' && 'code' in e.detail && e.detail.code === 'log_pattern_scan_limit') {
            result = 'scan-limit'
          } else {
            onError(formatValidationMessage(e.message) ?? toErrorMessage(e))
          }
        } else {
          onError(toErrorMessage(e))
        }
        setPatterns({ condition: patternCondition, result })
      })
    }, PATTERN_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      request.abort()
    }
  }, [view, rangeError, patternCondition, onError])

  const downloadCsv = async () => {
    if (loading || data.total === 0) return
    const filters = getFilters()
    if (!filters) return
    onError(null)
    setDownloadStarted(false)
    try {
      // ダウンロードはブラウザに任せる（401 や利用者の切り替わりを扱えないので、先に確かめる）
      downloadLogCsv(await prepareBrowserRequest(buildLogExportUrl(filters, timeZone)))
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
    if (view !== 'list') return
    let cancelled = false
    void (async () => {
      const filters = getFilters()
      if (cancelled) return
      if (!filters) { setLoading(false); return }
      const params = buildLogListSearchParams(filters, pageSize, page * pageSize)
      setLoading(true); onError(null)
      let correctingPage = false
      try {
        const raw = await apiGet<unknown>(`/api/logs?${params}`)
        if (cancelled) return
        const next = pageSchema.parse(raw)
        if (page > 0 && page * pageSize >= next.total) {
          // Keep loading until the corrected page has been fetched.
          correctingPage = true
          setPage(Math.max(0, Math.ceil(next.total / pageSize) - 1))
          return
        }
        setData(next)
      } catch (e) {
        if (!cancelled) onError(toErrorMessage(e))
      } finally {
        if (!cancelled && !correctingPage) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [view, getFilters, onError, page, pageSize])

  return <div className="panel logs-panel">
    <div className="toolbar" aria-label="ログの操作">
      <div className="logs-panel__view" role="group" aria-label="ログの表示">
        <button type="button" className={view === 'list' ? 'btn btn--filled' : 'btn btn--gray'} aria-pressed={view === 'list'} onClick={() => setView('list')}>一覧</button>
        <button type="button" className={view === 'patterns' ? 'btn btn--filled' : 'btn btn--gray'} aria-pressed={view === 'patterns'} onClick={() => setView('patterns')}>型ごと</button>
      </div>
      <label>vCenter<select value={vcenter} onChange={(e) => {
        setVcenterSelection(e.target.value)
        if (selectedPattern) clearPattern(e.target.value)
        else setPage(0)
      }}><option value="">全て</option>{vcenters.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select></label>
      {view === 'list' && <>
        <label>
          表示件数
          <select value={pageSize} onChange={(e) => {
            setPageSize(Number(e.target.value) as (typeof EVENT_PAGE_SIZES)[number])
            setPage(0)
          }}>
            {EVENT_PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <Pagination position="top" {...pagination} />
        <button type="button" className="btn btn--gray" disabled={loading || !resolvedRange.ok || data.total === 0} onClick={() => void downloadCsv()}>
          CSVをダウンロード
        </button>
        {downloadStarted && <span role="status" className="toolbar__meta">ダウンロードを開始しました。進捗・完了はブラウザで確認してください。</span>}
      </>}
      {vcenter && from && to && <a className="btn btn--gray logs-panel__event-link" href={correlationHash('events', { vcenterId: vcenter, from, to })}>同じ期間のイベント</a>}
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
    {selectedPattern && view === 'list' && <div className="logs-panel__pattern-filter">
      <span className="hint">型で絞り込み中（{selectedPattern.template ? <code>{selectedPattern.template}</code> : patternKeyLabel}）</span>
      <button type="button" className="btn btn--gray" onClick={() => clearPattern()}>型の絞り込みを解除</button>
    </div>}
    {view === 'patterns' ? (
      !resolvedRange.ok ? null
        : !from || !to ? <p className="table-empty">型ごとの集計には、絞り込み条件で期間の開始と終了を指定してください。</p>
        : patternResult === 'scan-limit' ? <p className="hint" role="note">対象のログが多すぎて集計できません。期間を短くするか、条件を追加して絞り込んでください。</p>
        : patternResult === 'busy' ? <p className="hint" role="status">集計が混み合っています。しばらくしてから再度お試しください。</p>
        : patternResult === 'error' ? null
        : patternResult === null ? <p role="status" className="table-empty">読み込み中…</p>
        : <LogPatternsTable data={patternResult} timeZone={timeZone} onSelect={openPattern} />
    ) : <>
      {data.items.length === 0 ? <p className="table-empty">条件に一致するログはありません</p> : <div className="logs-panel__table-scroll"><table className="table"><thead><tr><th>時刻</th><th>接続先</th><th>種別</th><th>重大度</th><th>本文</th></tr></thead><tbody>
        {data.items.map((r) => <tr key={r.id}>
          <td>{formatIsoInTimeZone(r.effective_at, timeZone)}{!r.occurred_at && <small>発生時刻未解析（取得時刻）</small>}</td>
          <td>{r.host}<small>{r.source_id}</small></td><td>{r.log_kind}</td><td><SeverityBadge severity={r.severity} /></td>
          <td><details><summary>{r.message.split('\n')[0].slice(0, 160)}</summary><pre>{r.message}</pre><small>世代: {r.file_generation} / バイト位置: {r.byte_offset}</small><p><a href={correlationHash('events', { vcenterId: r.vcenter_id, from: new Date(Date.parse(r.effective_at) - 300_000).toISOString(), to: new Date(Date.parse(r.effective_at) + 300_000).toISOString() })}>前後5分のイベント</a></p></details></td>
        </tr>)}
      </tbody></table></div>}
      {data.total > 0 && <Pagination position="bottom" {...pagination} />}
    </>}
  </div>
}
