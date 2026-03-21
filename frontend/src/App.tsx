import { useCallback, useEffect, useState } from 'react'
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
import { TimeZoneProvider, TimeZoneSelect, useTimeZone } from './datetime/TimeZoneContext'
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

type MetricPoint = {
  sampled_at: string
  value: number
  entity_name: string
  metric_key: string
  vcenter_id: string
}

type MetricSeriesResponse = {
  points: MetricPoint[]
  total: number
}

type Tab = 'summary' | 'events' | 'vcenters' | 'metrics'

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [tokenInput, setTokenInput] = useState(getToken)
  const [err, setErr] = useState<string | null>(null)

  const applyToken = () => {
    setToken(tokenInput.trim())
    setErr(null)
  }

  return (
    <TimeZoneProvider>
      <div className="app">
        <header className="header">
          <h1>vCenter Event Assistant</h1>
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
            <button type="button" onClick={applyToken}>
              保存
            </button>
            <TimeZoneSelect />
          </div>
        </header>

      {err && <div className="error-banner">{err}</div>}

      <nav className="tabs">
        {(['summary', 'events', 'vcenters', 'metrics'] as const).map((t) => (
          <button
            key={t}
            type="button"
            className={tab === t ? 'active' : ''}
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
        {tab === 'vcenters' && <VCentersPanel onError={setErr} />}
        {tab === 'metrics' && <MetricsPanel onError={setErr} />}
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
    void load()
  }, [load])

  if (!data) return <p>読み込み中…</p>

  return (
    <div className="panel">
      <p>
        <button type="button" onClick={() => void load()}>
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
          {data.high_cpu_hosts.map((h, i) => (
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
          {data.top_notable_events.map((e) => (
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
  const [minScore, setMinScore] = useState('')

  const load = useCallback(async () => {
    onError(null)
    try {
      const q = new URLSearchParams({ limit: '100' })
      if (minScore) q.set('min_score', minScore)
      const list = await apiGet<EventRow[]>(`/api/events?${q.toString()}`)
      setRows(list)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [onError, minScore])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          最小スコア
          <input
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            placeholder="例: 40"
          />
        </label>
        <button type="button" onClick={() => void load()}>
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
          {rows.map((e) => (
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
      const data = await apiGet<VCenter[]>('/api/vcenters')
      setList(data)
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e))
    }
  }, [onError])

  useEffect(() => {
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
      <button type="button" onClick={() => void add()}>
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
                <button type="button" onClick={() => void test(v.id)}>
                  接続テスト
                </button>
                <button
                  type="button"
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
                <button type="button" onClick={() => void remove(v.id)}>
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

  useEffect(() => {
    void apiGet<VCenter[]>('/api/vcenters')
      .then((v) => {
        setVcenters(v)
        setVcenterId((prev) => prev || v[0]?.id || '')
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)))
  }, [onError])

  const load = useCallback(async () => {
    setLoading(true)
    onError(null)
    try {
      const q = new URLSearchParams({ metric_key: metricKey, limit: '500' })
      if (vcenterId) q.set('vcenter_id', vcenterId)
      const data = await apiGet<MetricSeriesResponse>(`/api/metrics?${q.toString()}`)
      setPoints(data.points)
      setMetricTotal(data.total)
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
      await apiPost<{ status: string; events_inserted: string; metrics_inserted: string }>(
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

  const chartData = points.map((p) => ({
    t: formatIsoInTimeZone(p.sampled_at, timeZone),
    v: p.value,
    name: p.entity_name,
  }))

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
        <button type="button" disabled={loading} onClick={() => void load()}>
          {loading ? '取得中…' : '再取得'}
        </button>
        <button type="button" disabled={ingesting} onClick={() => void runIngest()}>
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
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="t" minTickGap={24} />
            <YAxis domain={[0, 100]} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="v" name="値" stroke="#0d6efd" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
