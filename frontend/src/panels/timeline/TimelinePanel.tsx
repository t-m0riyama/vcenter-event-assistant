import { useCallback, useEffect, useState } from 'react'
import './TimelinePanel.css'

import { apiGet, apiPost } from '../../api'
import { buildIncidentTimelineBuildRequestPayload } from '../../api/buildIncidentTimelineBuildRequestPayload'
import { parseIncidentTimelineResponse, type IncidentTimeline, type VCenter } from '../../api/schemas'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { resolveEventApiRange } from '../../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../../datetime/zonedRangeParts'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import { asArray } from '../../utils/asArray'
import { IncidentTimelinePanel } from '../chat/IncidentTimelinePanel'

const DEFAULT_METRIC_THRESHOLD_CPU_PCT = 80
const DEFAULT_METRIC_THRESHOLD_MEMORY_PCT = 85
const DEFAULT_METRIC_THRESHOLD_DISK_PCT = 75
const DEFAULT_METRIC_THRESHOLD_NETWORK_PCT = 75
const DEFAULT_ALERT_TOP_N = 7
const TIMELINE_SORT_ORDER_STORAGE_KEY = 'vea.timeline.sort_order'
type TimelineSortOrder = 'asc' | 'desc'

function isValidMetricThresholdPercent(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 100
}

export function TimelinePanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(METRICS_DEFAULT_ROLLING_DURATION_MS, 'UTC'),
  )
  const [vcenterId, setVcenterId] = useState<string>('')
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [timeline, setTimeline] = useState<IncidentTimeline | null>(null)
  const [loading, setLoading] = useState(false)

  const [includePeriodMetricsCpu, setIncludePeriodMetricsCpu] = useState(false)
  const [includePeriodMetricsMemory, setIncludePeriodMetricsMemory] = useState(false)
  const [includePeriodMetricsDiskIo, setIncludePeriodMetricsDiskIo] = useState(false)
  const [includePeriodMetricsNetworkIo, setIncludePeriodMetricsNetworkIo] = useState(false)

  const [metricThresholdCpuPct, setMetricThresholdCpuPct] = useState(DEFAULT_METRIC_THRESHOLD_CPU_PCT)
  const [metricThresholdCpuInput, setMetricThresholdCpuInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_CPU_PCT),
  )
  const [metricThresholdMemoryPct, setMetricThresholdMemoryPct] = useState(
    DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  )
  const [metricThresholdMemoryInput, setMetricThresholdMemoryInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_MEMORY_PCT),
  )
  const [metricThresholdDiskPct, setMetricThresholdDiskPct] = useState(DEFAULT_METRIC_THRESHOLD_DISK_PCT)
  const [metricThresholdDiskInput, setMetricThresholdDiskInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_DISK_PCT),
  )
  const [metricThresholdNetworkPct, setMetricThresholdNetworkPct] = useState(
    DEFAULT_METRIC_THRESHOLD_NETWORK_PCT,
  )
  const [metricThresholdNetworkInput, setMetricThresholdNetworkInput] = useState(
    String(DEFAULT_METRIC_THRESHOLD_NETWORK_PCT),
  )
  const [alertTopN, setAlertTopN] = useState(DEFAULT_ALERT_TOP_N)
  const [alertTopNInput, setAlertTopNInput] = useState(String(DEFAULT_ALERT_TOP_N))
  const [sortOrder, setSortOrder] = useState<TimelineSortOrder>(() => {
    if (typeof localStorage === 'undefined') {
      return 'desc'
    }
    const raw = localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY)
    return raw === 'asc' ? 'asc' : 'desc'
  })

  useEffect(() => {
    if (typeof localStorage === 'undefined') {
      return
    }
    localStorage.setItem(TIMELINE_SORT_ORDER_STORAGE_KEY, sortOrder)
  }, [sortOrder])

  useEffect(() => {
    void (async () => {
      try {
        const raw = await apiGet<unknown>('/api/vcenters')
        setVcenters(asArray<VCenter>(raw))
      } catch (e) {
        onError(toErrorMessage(e))
      }
    })()
  }, [onError])

  const handleMetricThresholdInputChange = useCallback(
    (
      rawValue: string,
      setInput: (value: string) => void,
      setValue: (value: number) => void,
    ) => {
      setInput(rawValue)
      if (rawValue.trim() === '') return
      const parsed = Number(rawValue)
      if (!isValidMetricThresholdPercent(parsed)) return
      setValue(parsed)
    },
    [],
  )

  const generateTimeline = useCallback(async () => {
    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    if (!resolved.from || !resolved.to) {
      onError('期間の開始と終了を指定してください。')
      return
    }

    onError(null)
    setLoading(true)
    try {
      const payload = buildIncidentTimelineBuildRequestPayload({
        resolvedRange: { from: resolved.from, to: resolved.to },
        options: {
          vcenterId,
          includePeriodMetricsCpu,
          includePeriodMetricsMemory,
          includePeriodMetricsDiskIo,
          includePeriodMetricsNetworkIo,
          metricThresholdCpuPct,
          metricThresholdMemoryPct,
          metricThresholdDiskPct,
          metricThresholdNetworkPct,
          alertTopN,
        },
      })
      const raw = await apiPost<unknown>('/api/incident-timeline', payload)
      const out = parseIncidentTimelineResponse(raw)
      setTimeline(out)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [
    includePeriodMetricsCpu,
    includePeriodMetricsDiskIo,
    includePeriodMetricsMemory,
    includePeriodMetricsNetworkIo,
    metricThresholdCpuPct,
    metricThresholdDiskPct,
    metricThresholdMemoryPct,
    metricThresholdNetworkPct,
    alertTopN,
    onError,
    rangeParts,
    timeZone,
    vcenterId,
  ])

  return (
    <div className="panel timeline-panel">
      <section className="timeline-panel__section" aria-label="集計期間">
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </section>

      <section className="timeline-panel__section" aria-label="vCenter">
        <label>
          対象 vCenter
          <select
            value={vcenterId}
            onChange={(e) => {
              setVcenterId(e.target.value)
            }}
          >
            <option value="">すべて（登録済み全体の集約）</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="timeline-panel__section" aria-label="期間メトリクス">
        <p className="hint timeline-panel__metrics-hint">
          タイムライン生成に含めるメトリクス（期間内をバケット平均で集約）
        </p>
        <label className="timeline-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsCpu}
            onChange={(e) => setIncludePeriodMetricsCpu(e.target.checked)}
            disabled={loading}
          />
          CPU 使用率
        </label>
        <label className="timeline-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsMemory}
            onChange={(e) => setIncludePeriodMetricsMemory(e.target.checked)}
            disabled={loading}
          />
          メモリ使用率
        </label>
        <label className="timeline-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsDiskIo}
            onChange={(e) => setIncludePeriodMetricsDiskIo(e.target.checked)}
            disabled={loading}
          />
          ディスク IO
        </label>
        <label className="timeline-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsNetworkIo}
            onChange={(e) => setIncludePeriodMetricsNetworkIo(e.target.checked)}
            disabled={loading}
          />
          ネットワーク IO
        </label>
      </section>

      <section className="timeline-panel__section" aria-label="メトリクス閾値">
        <p className="hint timeline-panel__metrics-hint">インシデント判定に使う閾値（%）</p>
        <div className="timeline-panel__threshold-grid">
          <label className="timeline-panel__threshold-field">
            CPU 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdCpuInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdCpuInput,
                  setMetricThresholdCpuPct,
                )
              }
              onBlur={() => setMetricThresholdCpuInput(String(metricThresholdCpuPct))}
              disabled={loading}
            />
          </label>
          <label className="timeline-panel__threshold-field">
            Memory 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdMemoryInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdMemoryInput,
                  setMetricThresholdMemoryPct,
                )
              }
              onBlur={() => setMetricThresholdMemoryInput(String(metricThresholdMemoryPct))}
              disabled={loading}
            />
          </label>
          <label className="timeline-panel__threshold-field">
            Disk 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdDiskInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdDiskInput,
                  setMetricThresholdDiskPct,
                )
              }
              onBlur={() => setMetricThresholdDiskInput(String(metricThresholdDiskPct))}
              disabled={loading}
            />
          </label>
          <label className="timeline-panel__threshold-field">
            Network 閾値（%）
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              value={metricThresholdNetworkInput}
              onChange={(e) =>
                handleMetricThresholdInputChange(
                  e.target.value,
                  setMetricThresholdNetworkInput,
                  setMetricThresholdNetworkPct,
                )
              }
              onBlur={() => setMetricThresholdNetworkInput(String(metricThresholdNetworkPct))}
              disabled={loading}
            />
          </label>
        </div>
      </section>

      <section className="timeline-panel__section" aria-label="表示オプション">
        <label className="timeline-panel__threshold-field">
          アラート上位件数
          <input
            type="number"
            min={1}
            max={20}
            step={1}
            value={alertTopNInput}
            onChange={(e) => {
              const rawValue = e.target.value
              setAlertTopNInput(rawValue)
              if (rawValue.trim() === '') {
                return
              }
              const parsed = Number(rawValue)
              if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
                return
              }
              setAlertTopN(parsed)
            }}
            onBlur={() => setAlertTopNInput(String(alertTopN))}
            disabled={loading}
          />
        </label>
        <button
          type="button"
          className="btn btn--gray"
          onClick={() => {
            setSortOrder((current) => (current === 'asc' ? 'desc' : 'asc'))
          }}
          disabled={loading}
        >
          {sortOrder === 'asc' ? '表示順: 昇順' : '表示順: 降順'}
        </button>
      </section>

      <div className="timeline-panel__actions">
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => void generateTimeline()}
          disabled={loading}
          aria-busy={loading ? 'true' : 'false'}
        >
          {loading ? 'タイムライン生成中' : 'タイムラインを生成'}
        </button>
      </div>

      {timeline ? (
        <IncidentTimelinePanel timeline={timeline} sortOrder={sortOrder} />
      ) : (
        <p className="hint">
          「タイムラインを生成」を押すと、指定期間のインシデント統合タイムラインを表示します。
        </p>
      )}
    </div>
  )
}
