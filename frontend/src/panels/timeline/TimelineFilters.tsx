import type { VCenter } from '../../api/schemas'
import { ZonedRangeFields, type ZonedRangeParts } from '../../datetime/ZonedRangeFields'

type TimelineFiltersProps = {
  rangeParts: ZonedRangeParts
  setRangeParts: (next: ZonedRangeParts) => void
  vcenters: VCenter[]
  vcenterId: string
  setVcenterId: (value: string) => void
  loading: boolean
  includePeriodMetricsCpu: boolean
  setIncludePeriodMetricsCpu: (value: boolean) => void
  includePeriodMetricsMemory: boolean
  setIncludePeriodMetricsMemory: (value: boolean) => void
  includePeriodMetricsDiskIo: boolean
  setIncludePeriodMetricsDiskIo: (value: boolean) => void
  includePeriodMetricsNetworkIo: boolean
  setIncludePeriodMetricsNetworkIo: (value: boolean) => void
  metricThresholdCpuInput: string
  metricThresholdCpuPct: number
  setMetricThresholdCpuInput: (value: string) => void
  setMetricThresholdCpuPct: (value: number) => void
  metricThresholdMemoryInput: string
  metricThresholdMemoryPct: number
  setMetricThresholdMemoryInput: (value: string) => void
  setMetricThresholdMemoryPct: (value: number) => void
  metricThresholdDiskInput: string
  metricThresholdDiskPct: number
  setMetricThresholdDiskInput: (value: string) => void
  setMetricThresholdDiskPct: (value: number) => void
  metricThresholdNetworkInput: string
  metricThresholdNetworkPct: number
  setMetricThresholdNetworkInput: (value: string) => void
  setMetricThresholdNetworkPct: (value: number) => void
  alertTopNInput: string
  alertTopN: number
  setAlertTopNInput: (value: string) => void
  setAlertTopN: (value: number) => void
  sortOrder: 'asc' | 'desc'
  setSortOrder: (value: 'asc' | 'desc' | ((current: 'asc' | 'desc') => 'asc' | 'desc')) => void
  onMetricThresholdInputChange: (
    rawValue: string,
    setInput: (value: string) => void,
    setValue: (value: number) => void,
  ) => void
  onAlertTopNInputChange: (rawValue: string) => void
  onAlertTopNBlur: () => void
}

/** タイムライン生成条件（期間・vCenter・メトリクス閾値等）の入力フォーム。 */
export function TimelineFilters({
  rangeParts,
  setRangeParts,
  vcenters,
  vcenterId,
  setVcenterId,
  loading,
  includePeriodMetricsCpu,
  setIncludePeriodMetricsCpu,
  includePeriodMetricsMemory,
  setIncludePeriodMetricsMemory,
  includePeriodMetricsDiskIo,
  setIncludePeriodMetricsDiskIo,
  includePeriodMetricsNetworkIo,
  setIncludePeriodMetricsNetworkIo,
  metricThresholdCpuInput,
  metricThresholdCpuPct,
  setMetricThresholdCpuInput,
  setMetricThresholdCpuPct,
  metricThresholdMemoryInput,
  metricThresholdMemoryPct,
  setMetricThresholdMemoryInput,
  setMetricThresholdMemoryPct,
  metricThresholdDiskInput,
  metricThresholdDiskPct,
  setMetricThresholdDiskInput,
  setMetricThresholdDiskPct,
  metricThresholdNetworkInput,
  metricThresholdNetworkPct,
  setMetricThresholdNetworkInput,
  setMetricThresholdNetworkPct,
  alertTopNInput,
  sortOrder,
  setSortOrder,
  onMetricThresholdInputChange,
  onAlertTopNInputChange,
  onAlertTopNBlur,
}: TimelineFiltersProps) {
  return (
    <>
      <section className="timeline-panel__section" aria-label="集計期間">
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </section>

      <section className="timeline-panel__section" aria-label="vCenter">
        <label>
          対象 vCenter
          <select value={vcenterId} onChange={(e) => setVcenterId(e.target.value)}>
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
                onMetricThresholdInputChange(
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
                onMetricThresholdInputChange(
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
                onMetricThresholdInputChange(
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
                onMetricThresholdInputChange(
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
            onChange={(e) => onAlertTopNInputChange(e.target.value)}
            onBlur={onAlertTopNBlur}
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
    </>
  )
}
