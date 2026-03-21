import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  getToken,
  setToken,
} from './api'
import { formatIsoInTimeZone } from './datetime/formatIsoInTimeZone'
import { TimeZoneProvider, TimeZoneSelect } from './datetime/TimeZoneProvider'
import { useTimeZone } from './datetime/useTimeZone'
import { MetricsChartErrorBoundary } from './metrics/MetricsChartErrorBoundary'
import {
  normalizeMetricSeriesResponse,
  type MetricPoint,
} from './metrics/normalizeMetricSeriesResponse'
import { CHART_STROKE_GRID, CHART_STROKE_PRIMARY } from './styles/chartStrokes'
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
}

type Summary = {
  vcenter_count: number
  events_last_24h: number
  notable_events_last_24h: number
  top_notable_events: EventRow[]
  high_cpu_hosts: Array<{
    vcenter_id: string
    entity_name: string
    value: number
    sampled_at: string
  }>
}

type AppConfig = {
  event_retention_days: number
  metric_retention_days: number
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

type Tab = 'summary' | 'events' | 'metrics' | 'vcenters'

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [tokenInput, setTokenInput] = useState(getToken)
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
    void loadConfig()
  }, [loadConfig])

  const applyToken = () => {
    setToken(tokenInput.trim())
    setErr(null)
    void loadConfig()
  }

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
          <div className="auth-row">
            <label>
              Bearer トークン（設定時は必須）
              <input
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="未設定の場合は認証なし（開発用）"
              />
            </label>
            <button type="button" className="btn btn--filled" onClick={applyToken}>
              保存
            </button>
            <TimeZoneSelect />
          </div>
        </header>

      {err && (
        <div className="error-banner" role="alert">
          {err}
        </div>
      )}

      <nav className="tabs">
        {(['summary', 'events', 'metrics', 'vcenters'] as const).map((t) => (
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
            {t === 'vcenters' && 'vCenter'}
            {t === 'metrics' && 'メトリクス'}
          </button>
        ))}
      </nav>

      <main className="main">
        {tab === 'summary' && <SummaryPanel onError={setErr} />}
        {tab === 'events' && <EventsPanel onError={setErr} />}
        {tab === 'metrics' && <MetricsPanel onError={setErr} />}
        {tab === 'vcenters' && <VCentersPanel onError={setErr} />}
      </main>
      </div>
    </TimeZoneProvider>
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

  return (
    <div className="panel">
      <p>
        <button type="button" className="btn btn--filled" onClick={() => void load()}>
          再読込
        </button>
      </p>
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

      <h2>高 CPU ホスト（直近24h サンプル上位）</h2>
      <table className="table">
        <thead>
          <tr>
            <th>ホスト</th>
            <th>CPU %</th>
            <th>時刻</th>
          </tr>
        </thead>
        <tbody>
          {asArray<Summary['high_cpu_hosts'][number]>(data.high_cpu_hosts).map((h, i) => (
            <tr key={`${h.entity_name}-${i}`}>
              <td>{h.entity_name}</td>
              <td>{h.value.toFixed(1)}</td>
              <td>{formatIsoInTimeZone(h.sampled_at, timeZone)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>要注意イベント（上位）</h2>
      <table className="table">
        <thead>
          <tr>
            <th>時刻</th>
            <th>種別</th>
            <th>スコア</th>
            <th>メッセージ</th>
          </tr>
        </thead>
        <tbody>
          {asArray<EventRow>(data.top_notable_events).map((e) => (
            <tr key={e.id}>
              <td>{formatIsoInTimeZone(e.occurred_at, timeZone)}</td>
              <td>{e.event_type}</td>
              <td>{e.notable_score}</td>
              <td className="msg">{e.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EventsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rows, setRows] = useState<EventRow[]>([])
  const [total, setTotal] = useState(0)
  const [minScore, setMinScore] = useState('')
  const [pageSize, setPageSize] = useState<(typeof EVENT_PAGE_SIZES)[number]>(50)
  const [page, setPage] = useState(1)

  const load = useCallback(async () => {
    onError(null)
    try {
      const q = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      })
      if (minScore) q.set('min_score', minScore)
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
  }, [onError, minScore, page, pageSize])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
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
        <button type="button" className="btn btn--filled" onClick={() => void load()}>
          再読込
        </button>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>時刻</th>
            <th>種別</th>
            <th>重大度</th>
            <th>スコア</th>
            <th>メッセージ</th>
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
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
                  onClick={() =>
                    void apiPatch(`/api/vcenters/${v.id}`, {
                      is_enabled: !v.is_enabled,
                    })
                      .then(load)
                      .catch((e) =>
                        onError(e instanceof Error ? e.message : String(e)),
                      )
                  }
                >
                  切替
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

function MetricsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [vcenterId, setVcenterId] = useState('')
  const [metricKey, setMetricKey] = useState('host.cpu.usage_pct')
  const [points, setPoints] = useState<MetricPoint[]>([])
  const [metricTotal, setMetricTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [chartResetKey, setChartResetKey] = useState(0)

  useEffect(() => {
    void apiGet<unknown>('/api/vcenters')
      .then((v) => {
        const arr = asArray<VCenter>(v)
        setVcenters(arr)
        setVcenterId((prev) => prev || arr[0]?.id || '')
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)))
  }, [onError])

  const load = useCallback(async () => {
    setLoading(true)
    onError(null)
    try {
      const q = new URLSearchParams({ metric_key: metricKey, limit: '500' })
      if (vcenterId) q.set('vcenter_id', vcenterId)
      const data = await apiGet<unknown>(`/api/metrics?${q.toString()}`)
      const normalized = normalizeMetricSeriesResponse(data)
      setPoints(normalized.points)
      setMetricTotal(normalized.total)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [vcenterId, metricKey, onError])

  useEffect(() => {
    void load()
  }, [load])

  const runIngest = async () => {
    setIngesting(true)
    onError(null)
    try {
      await apiPost<{ status: string; events_inserted: number; metrics_inserted: number }>(
        '/api/ingest/run',
        {},
      )
      await load()
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    } finally {
      setIngesting(false)
    }
  }

  const chartData = useMemo(
    () =>
      (points ?? [])
        .filter((p) => p != null && Number.isFinite(p.value))
        .map((p) => ({
          t: formatIsoInTimeZone(String(p.sampled_at), timeZone),
          v: p.value,
          name: p.entity_name ?? '',
        })),
    [points, timeZone],
  )

  return (
    <div className="panel">
      <p className="hint">
        メトリクスはバックグラウンド（既定で数分ごと）または「手動で収集」で vCenter
        から取り込まれます。vCenter が「有効」でないと収集されません。
      </p>
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
          <input
            value={metricKey}
            onChange={(e) => setMetricKey(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="btn btn--filled"
          disabled={loading}
          onClick={() => {
            setChartResetKey((k) => k + 1)
            void load()
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
        {metricTotal !== null && !loading && (
          <span className="metric-total">
            条件一致: {metricTotal} 件（表示: {points.length} 件まで）
          </span>
        )}
      </div>
      {!loading && metricTotal === 0 && (
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
        <div className="chart-wrap">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
              <CartesianGrid stroke={CHART_STROKE_GRID} strokeDasharray="3 3" />
              <XAxis dataKey="t" minTickGap={24} />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="v"
                name="値"
                stroke={CHART_STROKE_PRIMARY}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </MetricsChartErrorBoundary>
    </div>
  )
}
