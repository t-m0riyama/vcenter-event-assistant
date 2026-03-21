import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
} from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Text,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { apiDelete, apiGet, apiPatch, apiPost } from './api'
import {
  extractTickAxisValue,
  formatChartAxisTick,
  formatIsoInTimeZone,
  parseApiUtcInstantMs,
} from './datetime/formatIsoInTimeZone'
import { TimeZoneProvider, TimeZoneSelect } from './datetime/TimeZoneProvider'
import { useTimeZone } from './datetime/useTimeZone'
import { ZonedRangeFields } from './datetime/ZonedRangeFields'
import {
  isValidUtcRangeOrder,
  zonedLocalDateTimeToUtcIso,
} from './datetime/zonedLocalDateTime'
import {
  EMPTY_ZONED_RANGE_PARTS,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from './datetime/zonedRangeParts'
import { MetricsChartErrorBoundary } from './metrics/MetricsChartErrorBoundary'
import {
  buildMetricsExportBasename,
  downloadChartSvg,
} from './metrics/downloadChartSvg'
import {
  buildEventExportFilename,
  downloadEventListCsv,
  eventRowsToCsv,
} from './events/eventCsv'
import type { EventCsvRow } from './events/eventCsv'
import {
  bucketEpochUtcSec,
  downloadMetricPointsCsv,
  type MetricCsvExportOptions,
} from './metrics/metricCsv'
import {
  normalizeMetricSeriesResponse,
  type MetricPoint,
} from './metrics/normalizeMetricSeriesResponse'
import {
  CHART_STROKE_GRID,
  CHART_STROKE_PRIMARY,
  CHART_STROKE_SECONDARY,
} from './styles/chartStrokes'
import './App.css'

type VCenter = {
  id: string
  name: string
  host: string
  port: number
  username: string
  is_enabled: boolean
  created_at: string
}

type EventRow = {
  id: number
  vcenter_id: string
  occurred_at: string
  event_type: string
  message: string
  severity: string | null
  notable_score: number
  notable_tags: string[] | null
  user_name?: string | null
  entity_name?: string | null
  entity_type?: string | null
  user_comment?: string | null
}

type SummaryHostMetricRow = {
  vcenter_id: string
  entity_name: string
  entity_moid: string
  value: number
  sampled_at: string
}

type Summary = {
  vcenter_count: number
  events_last_24h: number
  notable_events_last_24h: number
  top_notable_events: EventRow[]
  high_cpu_hosts: SummaryHostMetricRow[]
  high_mem_hosts: SummaryHostMetricRow[]
  top_event_types_24h: Array<{
    event_type: string
    event_count: number
    max_notable_score: number
  }>
}

type AppConfig = {
  event_retention_days: number
  metric_retention_days: number
  perf_sample_interval_seconds: number
}

/** Coerce API fields to arrays so `.map` never runs on null / objects (runtime safety). */
function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : []
}

/** Accepts `{ items, total }` or a legacy JSON array so we never set `rows` to undefined (avoids render crash). */
function normalizeEventListPayload(raw: unknown): { items: EventRow[]; total: number } {
  if (Array.isArray(raw)) {
    return { items: raw as EventRow[], total: raw.length }
  }
  if (raw && typeof raw === 'object') {
    const o = raw as { items?: unknown; total?: unknown }
    const items = asArray<EventRow>(o.items)
    const total = typeof o.total === 'number' ? o.total : items.length
    return { items, total }
  }
  return { items: [], total: 0 }
}

const EVENT_PAGE_SIZES = [20, 50, 100, 200] as const

/** Matches `GET /api/events` max `limit` for chunked export. */
const EVENT_EXPORT_CHUNK = 200

const EVENT_TEXT_FILTER_SUMMARY_CLIP = 18
const EVENT_TEXT_FILTER_SUMMARY_MAX = 96

function clipForFilterSummary(s: string, max: number): string {
  const t = s.trim()
  if (!t) return ''
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`
}

/** One-line preview for collapsed 種別/重大度/メッセージ/コメント filters. */
function summarizeEventTextFilters(
  filterEventType: string,
  filterSeverity: string,
  filterMessage: string,
  filterComment: string,
): string {
  const pairs: Array<{ label: string; value: string }> = [
    { label: '種別', value: filterEventType },
    { label: '重大度', value: filterSeverity },
    { label: 'メッセージ', value: filterMessage },
    { label: 'コメント', value: filterComment },
  ]
  const active = pairs.filter((p) => p.value.trim())
  if (active.length === 0) return '条件なし'
  let out = active
    .map((p) => `${p.label}「${clipForFilterSummary(p.value, EVENT_TEXT_FILTER_SUMMARY_CLIP)}」`)
    .join(' · ')
  if (out.length > EVENT_TEXT_FILTER_SUMMARY_MAX) {
    out = `${out.slice(0, EVENT_TEXT_FILTER_SUMMARY_MAX - 1)}…`
  }
  return out
}

type EventRangeResolve =
  | { ok: true; from?: string; to?: string }
  | { ok: false; message: string }

/**
 * Maps optional wall-clock range inputs (display time zone) to API `from` / `to` UTC ISO strings.
 */
function resolveEventApiRange(
  rangeFromInput: string,
  rangeToInput: string,
  timeZone: string,
): EventRangeResolve {
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return { ok: true }
  let fromUtc: string | undefined
  let toUtc: string | undefined
  if (rf) {
    const iso = zonedLocalDateTimeToUtcIso(rf, timeZone)
    if (!iso) {
      return {
        ok: false,
        message:
          '開始の日付・時刻が解釈できないか、この時刻は存在しません（例: サマータイムの欠落時刻）。日付と時刻を確認してください。',
      }
    }
    fromUtc = iso
  }
  if (rt) {
    const iso = zonedLocalDateTimeToUtcIso(rt, timeZone)
    if (!iso) {
      return {
        ok: false,
        message:
          '終了の日付・時刻が解釈できないか、この時刻は存在しません（例: サマータイムの欠落時刻）。日付と時刻を確認してください。',
      }
    }
    toUtc = iso
  }
  if (fromUtc && toUtc && !isValidUtcRangeOrder(fromUtc, toUtc)) {
    return { ok: false, message: '開始は終了より前の時刻にしてください。' }
  }
  return { ok: true, from: fromUtc, to: toUtc }
}

type MetricsGraphRangeResolve =
  | { mode: 'none' }
  | { mode: 'range'; from: string; to: string }
  | { mode: 'invalid'; message: string }

/**
 * Graph tab: either both start/end are empty (no time filter), or both must be valid (same rules as events).
 * One-sided input is rejected so `GET /api/events/rate-series` can use the same bounds as metrics when a range is set.
 */
function resolveMetricsGraphRange(
  rangeFromInput: string,
  rangeToInput: string,
  timeZone: string,
): MetricsGraphRangeResolve {
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return { mode: 'none' }
  if (!rf || !rt) {
    return {
      mode: 'invalid',
      message:
        'グラフの表示期間は開始・終了を両方入力するか、両方空にしてください（片方だけでは指定できません）。',
    }
  }
  const r = resolveEventApiRange(rf, rt, timeZone)
  if (!r.ok) return { mode: 'invalid', message: r.message }
  if (!r.from || !r.to) {
    return { mode: 'invalid', message: '開始と終了を解釈できませんでした。' }
  }
  return { mode: 'range', from: r.from, to: r.to }
}

/** Graph tab: one-line summary for collapsed range `<details>` (no `open` = default closed). */
function summarizeGraphRangePreview(parts: ZonedRangeParts): string {
  const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(parts)
  const rf = rangeFromInput.trim()
  const rt = rangeToInput.trim()
  if (!rf && !rt) return '指定なし'
  if (!rf || !rt) return '入力中'
  return `${parts.fromDate} ～ ${parts.toDate}`
}

function eventRowToCsvRow(e: EventRow, vcenterName: string, timeZone: string): EventCsvRow {
  return {
    id: e.id,
    occurred_at: formatIsoInTimeZone(e.occurred_at, timeZone),
    vcenter_name: vcenterName,
    event_type: e.event_type,
    message: e.message,
    severity: e.severity,
    user_name: e.user_name ?? null,
    entity_name: e.entity_name ?? null,
    entity_type: e.entity_type ?? null,
    notable_score: e.notable_score,
    notable_tags: e.notable_tags as unknown[] | null,
    user_comment: e.user_comment ?? null,
  }
}

type Tab = 'summary' | 'events' | 'metrics' | 'settings'

type SettingsSubTab = 'general' | 'vcenters' | 'score_rules'

type EventScoreRuleRow = {
  id: number
  event_type: string
  score_delta: number
}

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('general')
  const [err, setErr] = useState<string | null>(null)
  const [retention, setRetention] = useState<AppConfig | null>(null)

  const loadConfig = useCallback(async () => {
    try {
      const c = await apiGet<AppConfig>('/api/config')
      setRetention(c)
    } catch (e) {
      setRetention(null)
      setErr(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void loadConfig()
  }, [loadConfig])

  return (
    <TimeZoneProvider>
      <div className="app">
        <header className="header">
          <h1>vCenter Event Assistant</h1>
          {retention && (
            <p className="retention-hint">
              データ保持: イベント {retention.event_retention_days} 日 / メトリクス{' '}
              {retention.metric_retention_days} 日（サーバー設定）
            </p>
          )}
        </header>

      {err && (
        <div className="error-banner" role="alert">
          {err}
        </div>
      )}

      <nav className="tabs">
        {(['summary', 'events', 'metrics', 'settings'] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={tab === t ? 'active' : undefined}
            onClick={() => {
              setTab(t)
              setErr(null)
            }}
          >
            {t === 'summary' && '概要'}
            {t === 'events' && 'イベント'}
            {t === 'metrics' && 'グラフ'}
            {t === 'settings' && '設定'}
          </button>
        ))}
      </nav>

      <main className="main">
        {tab === 'settings' && (
          <nav className="settings-subtabs" aria-label="設定">
            <button
              type="button"
              className={settingsSubTab === 'general' ? 'active' : undefined}
              aria-selected={settingsSubTab === 'general'}
              onClick={() => {
                setSettingsSubTab('general')
                setErr(null)
              }}
            >
              一般
            </button>
            <button
              type="button"
              className={settingsSubTab === 'vcenters' ? 'active' : undefined}
              aria-selected={settingsSubTab === 'vcenters'}
              onClick={() => {
                setSettingsSubTab('vcenters')
                setErr(null)
              }}
            >
              vCenter
            </button>
            <button
              type="button"
              className={settingsSubTab === 'score_rules' ? 'active' : undefined}
              aria-selected={settingsSubTab === 'score_rules'}
              onClick={() => {
                setSettingsSubTab('score_rules')
                setErr(null)
              }}
            >
              スコアルール
            </button>
          </nav>
        )}
        {tab === 'summary' && <SummaryPanel onError={setErr} />}
        {tab === 'events' && <EventsPanel onError={setErr} />}
        {tab === 'metrics' && (
          <MetricsPanel
            onError={setErr}
            perfBucketSeconds={retention?.perf_sample_interval_seconds ?? 300}
          />
        )}
        {tab === 'settings' && settingsSubTab === 'general' && <GeneralSettingsPanel />}
        {tab === 'settings' && settingsSubTab === 'score_rules' && (
          <ScoreRulesPanel onError={setErr} />
        )}
        {tab === 'settings' && settingsSubTab === 'vcenters' && (
          <VCentersPanel onError={setErr} />
        )}
      </main>
      </div>
    </TimeZoneProvider>
  )
}

function GeneralSettingsPanel() {
  return (
    <div className="panel">
      <p className="hint">
        日時の表示に使うタイムゾーンです。選択はこのブラウザに保存されます。
      </p>
      <TimeZoneSelect />
    </div>
  )
}

function SummaryPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [data, setData] = useState<Summary | null>(null)

  const load = useCallback(async () => {
    onError(null)
    try {
      const s = await apiGet<Summary>('/api/dashboard/summary')
      setData(s)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [onError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  if (!data) return <p>読み込み中…</p>

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
              <th>コメント</th>
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

function EventsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rows, setRows] = useState<EventRow[]>([])
  const [total, setTotal] = useState(0)
  const [minScore, setMinScore] = useState('')
  const [filterEventType, setFilterEventType] = useState('')
  const [filterSeverity, setFilterSeverity] = useState('')
  const [filterMessage, setFilterMessage] = useState('')
  const [filterComment, setFilterComment] = useState('')
  const [pageSize, setPageSize] = useState<(typeof EVENT_PAGE_SIZES)[number]>(50)
  const [page, setPage] = useState(1)
  const [editingCommentId, setEditingCommentId] = useState<number | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [exporting, setExporting] = useState(false)
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(EMPTY_ZONED_RANGE_PARTS)
  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )

  const load = useCallback(async () => {
    onError(null)
    try {
      const range = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!range.ok) {
        onError(range.message)
        return
      }
      const q = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      })
      if (minScore) q.set('min_score', minScore)
      const et = filterEventType.trim()
      if (et) q.set('event_type_contains', et)
      const sv = filterSeverity.trim()
      if (sv) q.set('severity_contains', sv)
      const msg = filterMessage.trim()
      if (msg) q.set('message_contains', msg)
      const cm = filterComment.trim()
      if (cm) q.set('comment_contains', cm)
      if (range.from) q.set('from', range.from)
      if (range.to) q.set('to', range.to)
      const raw = await apiGet<unknown>(`/api/events?${q.toString()}`)
      const { items, total: nextTotal } = normalizeEventListPayload(raw)
      setRows(items)
      setTotal(nextTotal)
      const maxPage =
        nextTotal === 0 ? 1 : Math.max(1, Math.ceil(nextTotal / pageSize))
      setPage((p) => (p > maxPage ? maxPage : p))
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [
    onError,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    page,
    pageSize,
    rangeFromInput,
    rangeToInput,
    timeZone,
  ])

  useEffect(() => {
    void load()
  }, [load])

  const { start, end, safePage } = useMemo(() => {
    if (total === 0) return { start: 0, end: 0, safePage: 1 }
    const maxPage = Math.max(1, Math.ceil(total / pageSize))
    const sp = Math.min(page, maxPage)
    const s = (sp - 1) * pageSize + 1
    const e = Math.min(sp * pageSize, total)
    return { start: s, end: e, safePage: sp }
  }, [page, pageSize, total])

  const canPrev = safePage > 1
  const canNext = total > 0 && safePage * pageSize < total

  useEffect(() => {
    setEditingCommentId(null)
    setCommentDraft('')
  }, [
    page,
    pageSize,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    rangeParts,
  ])

  const beginCommentEdit = (e: EventRow) => {
    setEditingCommentId(e.id)
    setCommentDraft(e.user_comment ?? '')
  }

  const cancelCommentEdit = () => {
    setEditingCommentId(null)
    setCommentDraft('')
  }

  const saveComment = async (eventId: number) => {
    onError(null)
    try {
      const updated = await apiPatch<EventRow>(`/api/events/${eventId}`, {
        user_comment: commentDraft.trim() === '' ? null : commentDraft,
      })
      setRows((prev) => prev.map((r) => (r.id === eventId ? { ...r, ...updated } : r)))
      setEditingCommentId(null)
      setCommentDraft('')
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const downloadCsv = useCallback(async () => {
    onError(null)
    setExporting(true)
    try {
      const range = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!range.ok) {
        onError(range.message)
        return
      }
      const vcenters = await apiGet<unknown>('/api/vcenters')
      const vcenterList = asArray<VCenter>(vcenters)
      const nameById = new Map(vcenterList.map((v) => [v.id, v.name]))

      const all: EventRow[] = []
      let offset = 0
      let totalExpected = 0
      for (;;) {
        const q = new URLSearchParams({
          limit: String(EVENT_EXPORT_CHUNK),
          offset: String(offset),
        })
        if (minScore) q.set('min_score', minScore)
        const et = filterEventType.trim()
        if (et) q.set('event_type_contains', et)
        const sv = filterSeverity.trim()
        if (sv) q.set('severity_contains', sv)
        const msg = filterMessage.trim()
        if (msg) q.set('message_contains', msg)
        const cm = filterComment.trim()
        if (cm) q.set('comment_contains', cm)
        if (range.from) q.set('from', range.from)
        if (range.to) q.set('to', range.to)
        const raw = await apiGet<unknown>(`/api/events?${q.toString()}`)
        const { items, total } = normalizeEventListPayload(raw)
        totalExpected = total
        all.push(...items)
        offset += items.length
        if (items.length === 0) break
        if (all.length >= totalExpected) break
      }
      all.sort(
        (a, b) =>
          parseApiUtcInstantMs(a.occurred_at) - parseApiUtcInstantMs(b.occurred_at),
      )
      const csv = eventRowsToCsv(
        all.map((e) =>
          eventRowToCsvRow(
            e,
            nameById.get(e.vcenter_id) ?? e.vcenter_id,
            timeZone,
          ),
        ),
      )
      downloadEventListCsv(csv, buildEventExportFilename())
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setExporting(false)
    }
  }, [
    onError,
    minScore,
    filterEventType,
    filterSeverity,
    filterMessage,
    filterComment,
    timeZone,
    rangeFromInput,
    rangeToInput,
  ])

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          最小スコア
          <input
            value={minScore}
            onChange={(e) => {
              setMinScore(e.target.value)
              setPage(1)
            }}
            placeholder="例: 40"
          />
        </label>
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
        <div className="toolbar__pagination">
          <button
            type="button"
            className="btn"
            disabled={!canPrev}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            前へ
          </button>
          <button
            type="button"
            className="btn"
            disabled={!canNext}
            onClick={() => setPage((p) => p + 1)}
          >
            次へ
          </button>
        </div>
        <span className="toolbar__meta">
          {total === 0 ? '全 0 件' : `全 ${total} 件中 ${start}–${end} 件を表示`}
        </span>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exporting || total === 0}
          onClick={() => void downloadCsv()}
        >
          {exporting ? '出力中…' : 'CSV をダウンロード'}
        </button>
        <details className="toolbar__filters-details">
          <summary className="toolbar__filters-summary">
            <span className="toolbar__filters-summary__title">絞り込み条件</span>
            <span className="toolbar__filters-summary__preview">
              {summarizeEventTextFilters(
                filterEventType,
                filterSeverity,
                filterMessage,
                filterComment,
              )}
            </span>
          </summary>
          <p className="hint toolbar__filters-hint">
            表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。未入力の端は制限なし。日付だけ選んだ場合は、開始は
            0:00・終了は 23:59 として扱います。クイックで直近の範囲を入れられます。
          </p>
          <ZonedRangeFields
            value={rangeParts}
            onChange={(next) => {
              setRangeParts(next)
              setPage(1)
            }}
          />
          <div className="toolbar__filters" aria-label="イベントの絞り込み（種別・重大度・メッセージ・コメント）">
            <label>
              種別（含む）
              <input
                value={filterEventType}
                onChange={(e) => {
                  setFilterEventType(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              重大度（含む）
              <input
                value={filterSeverity}
                onChange={(e) => {
                  setFilterSeverity(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              メッセージ（含む）
              <input
                value={filterMessage}
                onChange={(e) => {
                  setFilterMessage(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
            <label>
              コメント（含む）
              <input
                value={filterComment}
                onChange={(e) => {
                  setFilterComment(e.target.value)
                  setPage(1)
                }}
                placeholder="部分一致"
                autoComplete="off"
              />
            </label>
          </div>
        </details>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>時刻</th>
            <th>種別</th>
            <th>重大度</th>
            <th>スコア</th>
            <th>メッセージ</th>
            <th>コメント</th>
          </tr>
        </thead>
        <tbody>
          {asArray<EventRow>(rows).map((e) => (
            <tr key={e.id}>
              <td>{formatIsoInTimeZone(e.occurred_at, timeZone)}</td>
              <td>{e.event_type}</td>
              <td>{e.severity ?? ''}</td>
              <td>{e.notable_score}</td>
              <td className="msg">{e.message}</td>
              <td className="event-comment-cell">
                {editingCommentId === e.id ? (
                  <div className="event-comment-edit">
                    <textarea
                      className="event-comment-textarea"
                      value={commentDraft}
                      onChange={(ev) => setCommentDraft(ev.target.value)}
                      rows={3}
                      maxLength={8000}
                      aria-label="イベントコメント"
                    />
                    <div className="event-comment-actions">
                      <button
                        type="button"
                        className="btn btn--filled"
                        onClick={() => void saveComment(e.id)}
                      >
                        保存
                      </button>
                      <button type="button" className="btn" onClick={cancelCommentEdit}>
                        キャンセル
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="event-comment-view">
                    <span className="event-comment-preview">
                      {e.user_comment?.trim() ? e.user_comment : '—'}
                    </span>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => beginCommentEdit(e)}
                    >
                      編集
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ScoreRulesPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<EventScoreRuleRow[]>([])
  const [newType, setNewType] = useState('')
  const [newDelta, setNewDelta] = useState(0)
  const [draftDelta, setDraftDelta] = useState<Record<number, number>>({})

  const load = useCallback(async () => {
    onError(null)
    try {
      const data = await apiGet<EventScoreRuleRow[]>('/api/event-score-rules')
      setList(data)
      const d: Record<number, number> = {}
      for (const r of data) {
        d[r.id] = r.score_delta
      }
      setDraftDelta(d)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [onError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  const add = async () => {
    const et = newType.trim()
    if (!et) {
      onError('イベント種別を入力してください')
      return
    }
    onError(null)
    try {
      await apiPost('/api/event-score-rules', {
        event_type: et,
        score_delta: newDelta,
      })
      setNewType('')
      setNewDelta(0)
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const save = async (id: number) => {
    onError(null)
    try {
      const v = draftDelta[id]
      await apiPatch(`/api/event-score-rules/${id}`, {
        score_delta: typeof v === 'number' && Number.isFinite(v) ? v : 0,
      })
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const remove = async (id: number) => {
    if (!confirm('このルールを削除しますか？既存イベントのスコアはルールなしのベースに戻ります。')) return
    onError(null)
    try {
      await apiDelete(`/api/event-score-rules/${id}`)
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        イベント種別（event_type）ごとに、ルールベースのスコアへ加算する値を設定します。最終スコアは 0〜100
        に収まります。既存の取り込み済みイベントにも、ルールの保存・変更・削除時に再計算が反映されます。
      </p>
      <h2>追加</h2>
      <div className="form-grid score-rules-form">
        <label>
          イベント種別（完全一致）
          <input
            value={newType}
            onChange={(e) => setNewType(e.target.value)}
            placeholder="例: vim.event.VmPoweredOnEvent"
            autoComplete="off"
          />
        </label>
        <label>
          加算（負数可）
          <input
            type="number"
            value={newDelta}
            onChange={(e) => setNewDelta(Number(e.target.value))}
          />
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <table className="table">
        <thead>
          <tr>
            <th>イベント種別</th>
            <th>加算</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id}>
              <td className="msg">{r.event_type}</td>
              <td>
                <input
                  type="number"
                  className="score-rules-delta-input"
                  aria-label={`${r.event_type} の加算`}
                  value={draftDelta[r.id] ?? r.score_delta}
                  onChange={(e) =>
                    setDraftDelta((prev) => ({
                      ...prev,
                      [r.id]: Number(e.target.value),
                    }))
                  }
                />
              </td>
              <td className="actions">
                <button type="button" className="btn btn--filled" onClick={() => void save(r.id)}>
                  保存
                </button>
                <button type="button" className="btn btn--gray" onClick={() => void remove(r.id)}>
                  削除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** X 軸目盛り専用。`useTimeZone()` をここで読むことで Recharts の Redux 同期と親のクロージャに依存しない。 */
function MetricsXAxisTick(props: Record<string, unknown>) {
  const { timeZone } = useTimeZone()
  const { payload, ...rest } = props
  const label = formatChartAxisTick(extractTickAxisValue(payload), timeZone)
  return <Text {...(rest as ComponentProps<typeof Text>)}>{label}</Text>
}

function VCentersPanel({ onError }: { onError: (e: string | null) => void }) {
  const [list, setList] = useState<VCenter[]>([])
  const [form, setForm] = useState({
    name: '',
    host: '',
    port: 443,
    username: '',
    password: '',
    is_enabled: true,
  })

  const load = useCallback(async () => {
    onError(null)
    try {
      const data = await apiGet<unknown>('/api/vcenters')
      setList(asArray<VCenter>(data))
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [onError])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  const add = async () => {
    onError(null)
    try {
      await apiPost('/api/vcenters', form)
      setForm({ name: '', host: '', port: 443, username: '', password: '', is_enabled: true })
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const remove = async (id: string) => {
    if (!confirm('削除しますか？')) return
    onError(null)
    try {
      await apiDelete(`/api/vcenters/${id}`)
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const toggleEnabled = async (v: VCenter) => {
    const msg = v.is_enabled ? '無効にしますか？' : '有効にしますか？'
    if (!confirm(msg)) return
    onError(null)
    try {
      await apiPatch(`/api/vcenters/${v.id}`, {
        is_enabled: !v.is_enabled,
      })
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const test = async (id: string) => {
    onError(null)
    try {
      const r = await apiGet<Record<string, unknown>>(`/api/vcenters/${id}/test`)
      alert(JSON.stringify(r, null, 2))
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="panel">
      <h2>登録</h2>
      <div className="form-grid">
        <label>
          表示名
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </label>
        <label>
          ホスト
          <input
            value={form.host}
            onChange={(e) => setForm({ ...form, host: e.target.value })}
          />
        </label>
        <label>
          ポート
          <input
            type="number"
            value={form.port}
            onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
          />
        </label>
        <label>
          ユーザー
          <input
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
          />
        </label>
        <label>
          パスワード
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={form.is_enabled}
            onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })}
          />
          有効
        </label>
      </div>
      <button type="button" className="btn btn--filled" onClick={() => void add()}>
        追加
      </button>

      <h2>一覧</h2>
      <table className="table">
        <thead>
          <tr>
            <th>名前</th>
            <th>ホスト</th>
            <th>有効</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {list.map((v) => (
            <tr key={v.id}>
              <td>{v.name}</td>
              <td>
                {v.host}:{v.port}
              </td>
              <td>{v.is_enabled ? 'はい' : 'いいえ'}</td>
              <td className="actions">
                <button type="button" className="btn btn--gray" onClick={() => void test(v.id)}>
                  接続テスト
                </button>
                <button
                  type="button"
                  className="btn btn--gray"
                  onClick={() => void toggleEnabled(v)}
                >
                  {v.is_enabled ? '無効' : '有効'}
                </button>
                <button type="button" className="btn btn--gray" onClick={() => void remove(v.id)}>
                  削除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetricsPanel({
  onError,
  perfBucketSeconds,
}: {
  onError: (e: string | null) => void
  perfBucketSeconds: number
}) {
  const { timeZone } = useTimeZone()
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [vcenterId, setVcenterId] = useState('')
  const [metricKeys, setMetricKeys] = useState<string[]>([])
  const [metricKey, setMetricKey] = useState('')
  const [points, setPoints] = useState<MetricPoint[]>([])
  const [metricTotal, setMetricTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [chartResetKey, setChartResetKey] = useState(0)
  const [chartEventType, setChartEventType] = useState('')
  const [eventTypeOptions, setEventTypeOptions] = useState<string[]>([])
  const [eventRateBuckets, setEventRateBuckets] = useState<
    Array<{ bucket_start: string; count: number }> | null
  >(null)
  const [eventSeriesLoading, setEventSeriesLoading] = useState(false)
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(EMPTY_ZONED_RANGE_PARTS)
  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )
  const prevVcenterForKeysRef = useRef<string | undefined>(undefined)
  const lastSeriesFetchRef = useRef<{
    vcenterId: string
    metricKey: string
    rangeKey: string
  } | null>(null)
  const metricKeyRef = useRef(metricKey)
  const chartWrapRef = useRef<HTMLDivElement>(null)
  metricKeyRef.current = metricKey

  useEffect(() => {
    void apiGet<unknown>('/api/vcenters')
      .then((v) => {
        const arr = asArray<VCenter>(v)
        setVcenters(arr)
        setVcenterId((prev) => prev || arr[0]?.id || '')
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)))
  }, [onError])

  useEffect(() => {
    const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
    void apiGet<{ event_types?: unknown }>(`/api/events/event-types${q}`)
      .then((d) => setEventTypeOptions(asArray<string>(d.event_types)))
      .catch(() => setEventTypeOptions([]))
  }, [vcenterId])

  const loadMetricKeys = useCallback(async (): Promise<string> => {
    try {
      const q = vcenterId ? `?vcenter_id=${encodeURIComponent(vcenterId)}` : ''
      const data = await apiGet<{ metric_keys?: unknown }>(`/api/metrics/keys${q}`)
      const keys = asArray<string>(data.metric_keys)
      const prev = metricKeyRef.current
      const nextKey = keys.includes(prev) ? prev : keys[0] ?? ''
      setMetricKeys(keys)
      setMetricKey(nextKey)
      return nextKey
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
      setMetricKeys([])
      setMetricKey('')
      return ''
    }
  }, [vcenterId, onError])

  const load = useCallback(
    async (overrideKey?: string): Promise<boolean> => {
      const graphRange = resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone)
      if (graphRange.mode === 'invalid') {
        onError(graphRange.message)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      const key = (overrideKey ?? metricKey).trim()
      if (!key) {
        onError(null)
        setPoints([])
        setMetricTotal(null)
        setLoading(false)
        return false
      }
      setLoading(true)
      onError(null)
      try {
        const limit = graphRange.mode === 'range' ? '10000' : '500'
        const q = new URLSearchParams({ metric_key: key, limit })
        if (vcenterId) q.set('vcenter_id', vcenterId)
        if (graphRange.mode === 'range') {
          q.set('from', graphRange.from)
          q.set('to', graphRange.to)
        }
        const data = await apiGet<unknown>(`/api/metrics?${q.toString()}`)
        const normalized = normalizeMetricSeriesResponse(data)
        setPoints(normalized.points)
        setMetricTotal(normalized.total)
        return true
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e))
        return false
      } finally {
        setLoading(false)
      }
    },
    [vcenterId, metricKey, onError, rangeFromInput, rangeToInput, timeZone],
  )

  const graphRangeForOverlay = useMemo(
    () => resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone),
    [rangeFromInput, rangeToInput, timeZone],
  )

  useEffect(() => {
    void (async () => {
      let key = metricKey
      if (prevVcenterForKeysRef.current !== vcenterId) {
        prevVcenterForKeysRef.current = vcenterId
        key = await loadMetricKeys()
      }
      const rangeKey = `${rangeParts.fromDate}|${rangeParts.fromTime}|${rangeParts.toDate}|${rangeParts.toTime}`
      const sig = { vcenterId, metricKey: key, rangeKey }
      const prev = lastSeriesFetchRef.current
      if (
        prev &&
        prev.vcenterId === sig.vcenterId &&
        prev.metricKey === sig.metricKey &&
        prev.rangeKey === sig.rangeKey
      ) {
        return
      }
      const ok = await load(key)
      if (ok) lastSeriesFetchRef.current = sig
    })()
  }, [vcenterId, metricKey, load, loadMetricKeys, rangeParts])

  useEffect(() => {
    const et = chartEventType.trim()
    if (!et || points.length === 0) {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    if (graphRangeForOverlay.mode === 'invalid') {
      setEventRateBuckets(null)
      setEventSeriesLoading(false)
      return
    }
    let cancelled = false
    setEventSeriesLoading(true)
    void (async () => {
      let from: string
      let to: string
      if (graphRangeForOverlay.mode === 'range') {
        from = graphRangeForOverlay.from
        to = graphRangeForOverlay.to
      } else {
        let minTs = Infinity
        let maxTs = -Infinity
        for (const p of points) {
          const t = parseApiUtcInstantMs(p.sampled_at)
          if (Number.isFinite(t)) {
            if (t < minTs) minTs = t
            if (t > maxTs) maxTs = t
          }
        }
        if (!Number.isFinite(minTs) || !Number.isFinite(maxTs)) {
          if (!cancelled) {
            setEventRateBuckets(null)
            setEventSeriesLoading(false)
          }
          return
        }
        from = new Date(minTs).toISOString()
        to = new Date(maxTs).toISOString()
      }
      const fromMs = parseApiUtcInstantMs(from)
      const toMs = parseApiUtcInstantMs(to)
      if (fromMs >= toMs) {
        to = new Date(fromMs + Math.max(perfBucketSeconds, 60) * 1000).toISOString()
      }
      try {
        const q = new URLSearchParams({
          event_type: et,
          from,
          to,
          bucket_seconds: String(perfBucketSeconds),
        })
        if (vcenterId) q.set('vcenter_id', vcenterId)
        const data = await apiGet<{
          buckets?: Array<{ bucket_start: string; count: number }>
        }>(`/api/events/rate-series?${q.toString()}`)
        if (!cancelled) {
          setEventRateBuckets(Array.isArray(data.buckets) ? data.buckets : [])
          onError(null)
        }
      } catch (e) {
        if (!cancelled) {
          setEventRateBuckets(null)
          onError(e instanceof Error ? e.message : String(e))
        }
      } finally {
        if (!cancelled) setEventSeriesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [points, chartEventType, vcenterId, perfBucketSeconds, onError, graphRangeForOverlay])

  const runIngest = async () => {
    setIngesting(true)
    onError(null)
    try {
      await apiPost<{ status: string; events_inserted: number; metrics_inserted: number }>(
        '/api/ingest/run',
        {},
      )
      lastSeriesFetchRef.current = null
      const key = await loadMetricKeys()
      await load(key)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setIngesting(false)
    }
  }

  const countByEpochSec = useMemo(() => {
    const m = new Map<number, number>()
    if (!eventRateBuckets) return m
    for (const b of eventRateBuckets) {
      const sec = Math.floor(parseApiUtcInstantMs(String(b.bucket_start)) / 1000)
      m.set(sec, b.count)
    }
    return m
  }, [eventRateBuckets])

  const showEventLine =
    chartEventType.trim().length > 0 && eventRateBuckets != null && !eventSeriesLoading

  const chartData = useMemo(
    () =>
      (points ?? [])
        .filter((p) => {
          if (p == null || !Number.isFinite(p.value)) return false
          return Number.isFinite(parseApiUtcInstantMs(String(p.sampled_at)))
        })
        .map((p) => {
          const sampled = String(p.sampled_at)
          const tMs = parseApiUtcInstantMs(sampled)
          const bucketSec = bucketEpochUtcSec(sampled, perfBucketSeconds)
          const evCount = showEventLine ? (countByEpochSec.get(bucketSec) ?? 0) : 0
          return {
            tMs,
            v: p.value,
            evCount,
            name: p.entity_name ?? '',
          }
        }),
    [points, perfBucketSeconds, showEventLine, countByEpochSec],
  )

  const metricsChartLegendName = useMemo(() => {
    const keyPart = metricKey || '—'
    if (!vcenterId) {
      return `全て / ${keyPart}`
    }
    const v = vcenters.find((c) => c.id === vcenterId)
    const vcLabel = v?.name ?? vcenterId
    return `${vcLabel} / ${keyPart}`
  }, [vcenterId, vcenters, metricKey])

  const eventSeriesLegendName = useMemo(() => {
    const et = chartEventType.trim()
    if (!et) return 'イベント件数'
    return `イベント（${et}）`
  }, [chartEventType])

  const formatAxisTimeLabel = useCallback(
    (value: unknown) => formatChartAxisTick(value, timeZone),
    [timeZone],
  )

  const metricsXAxisTick = useCallback(
    (props: Record<string, unknown>) => <MetricsXAxisTick {...props} />,
    [],
  )

  const vcenterExportLabel = useMemo(() => {
    if (!vcenterId) return 'all'
    const v = vcenters.find((c) => c.id === vcenterId)
    return v?.name ?? vcenterId
  }, [vcenterId, vcenters])

  const csvExportOptions: MetricCsvExportOptions | undefined = useMemo(() => {
    const et = chartEventType.trim()
    if (!et || !eventRateBuckets) return undefined
    return {
      bucketSeconds: perfBucketSeconds,
      eventCountByBucketEpochSec: countByEpochSec,
      overlayEventType: et,
    }
  }, [chartEventType, eventRateBuckets, perfBucketSeconds, countByEpochSec])

  const exportDisabled =
    loading || !metricKey || points.length === 0 || eventSeriesLoading

  const downloadSvg = () => {
    try {
      const base = buildMetricsExportBasename(vcenterId, vcenterExportLabel, metricKey)
      downloadChartSvg(chartWrapRef.current, `${base}.svg`)
      onError(null)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  const downloadCsv = () => {
    try {
      const base = buildMetricsExportBasename(vcenterId, vcenterExportLabel, metricKey)
      downloadMetricPointsCsv(points, `${base}.csv`, csvExportOptions)
      onError(null)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          vCenter
          <select
            value={vcenterId}
            onChange={(e) => setVcenterId(e.target.value)}
          >
            <option value="">全て</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          メトリクスキー
          <select
            value={metricKey}
            disabled={metricKeys.length === 0}
            onChange={(e) => setMetricKey(e.target.value)}
          >
            {metricKeys.length === 0 ? (
              <option value="">収集済みメトリクスがありません</option>
            ) : (
              metricKeys.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))
            )}
          </select>
        </label>
        <label>
          イベント種別（任意・完全一致）
          <input
            type="text"
            value={chartEventType}
            onChange={(e) => setChartEventType(e.target.value)}
            list="metrics-event-type-options"
            placeholder="例: VmPoweredOnEvent"
            autoComplete="off"
          />
          <datalist id="metrics-event-type-options">
            {eventTypeOptions.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
        <button
          type="button"
          className="btn btn--filled"
          disabled={loading || !metricKey}
          onClick={() => {
            setChartResetKey((k) => k + 1)
            lastSeriesFetchRef.current = null
            void load(metricKey)
          }}
        >
          {loading ? '取得中…' : '再取得'}
        </button>
        <button
          type="button"
          className="btn btn--gray"
          disabled={ingesting}
          onClick={() => void runIngest()}
        >
          {ingesting ? '収集中…' : '手動で収集'}
        </button>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exportDisabled}
          onClick={downloadSvg}
        >
          グラフをダウンロード
        </button>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exportDisabled}
          onClick={downloadCsv}
        >
          CSV をダウンロード
        </button>
        {metricTotal !== null && !loading && (
          <span className="metric-total">
            条件一致: {metricTotal} 件（表示: {points.length} 件まで）
          </span>
        )}
      </div>
      <details className="toolbar__filters-details metrics-panel__range-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">表示期間</span>
          <span className="toolbar__filters-summary__preview">
            {summarizeGraphRangePreview(rangeParts)}
          </span>
        </summary>
        <p className="hint toolbar__filters-hint">
          表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。開始・終了は両方指定するか、すべて空にしてください。日付のみの場合は開始は
          0:00・終了は 23:59 です。期間を指定するとメトリクスは最大 10000
          点まで取得し、イベント件数オーバーレイも同じ区間で集計します。
        </p>
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </details>
      <p className="hint">
        イベント件数はサーバ設定のメトリクス取得間隔（{perfBucketSeconds}
        秒）と同じ幅のバケットに集計されます。種別を空にするとメトリクスのみ表示します。
      </p>
      {!loading && metricKeys.length === 0 && (
        <p className="hint">
          この条件で DB に保存されたメトリクスがありません。「手動で収集」を実行するか、スケジュール取り込みを待ってから再度開いてください。
        </p>
      )}
      {!loading && metricTotal === 0 && metricKey && (
        <div className="empty-metrics">
          <p>該当するメトリクスがありません（条件一致 0 件）。</p>
          <ul>
            <li>vCenter の「有効」がオンか確認してください。</li>
            <li>初回は「手動で収集」を押すか、数分待ってから「再取得」してください。</li>
            <li>接続情報・権限が正しいか、接続テストで確認してください。</li>
          </ul>
        </div>
      )}
      <MetricsChartErrorBoundary key={`${vcenterId}-${metricKey}-${chartResetKey}`}>
        <div className="chart-wrap" ref={chartWrapRef}>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart
              key={timeZone}
              data={chartData}
              margin={{ top: 8, right: 12, left: 4, bottom: 8 }}
            >
              <CartesianGrid stroke={CHART_STROKE_GRID} strokeDasharray="3 3" />
              <XAxis
                dataKey="tMs"
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                tickFormatter={formatAxisTimeLabel}
                tick={metricsXAxisTick}
                minTickGap={24}
              />
              <YAxis yAxisId="left" domain={['auto', 'auto']} />
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={['auto', 'auto']}
                allowDecimals={false}
              />
              <Tooltip labelFormatter={formatAxisTimeLabel} />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="v"
                name={metricsChartLegendName}
                stroke={CHART_STROKE_PRIMARY}
                dot={false}
                isAnimationActive={false}
              />
              {showEventLine && (
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="evCount"
                  name={eventSeriesLegendName}
                  stroke={CHART_STROKE_SECONDARY}
                  dot={false}
                  isAnimationActive={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </MetricsChartErrorBoundary>
    </div>
  )
}
