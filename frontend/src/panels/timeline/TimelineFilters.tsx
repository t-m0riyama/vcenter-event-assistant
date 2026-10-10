import type { VCenter } from '../../api/schemas'
import { ZonedRangeDetails } from '../../datetime/ZonedRangeDetails'
import type { ZonedRangeParts } from '../../datetime/ZonedRangeFields'

type TimelineFiltersProps = {
  rangeParts: ZonedRangeParts
  setRangeParts: (next: ZonedRangeParts) => void
  applyRollingPreset: (durationMs: number) => void
  rangeDisplayLabel: string
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
  applyRollingPreset,
  rangeDisplayLabel,
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
      {/* イベント・ログと同じツールバーの形（ラベルが上、入力欄が下で横に並べる）。 */}
      <div className="toolbar timeline-panel__toolbar" aria-label="タイムラインの条件">
        <label>
          vCenter
          <select value={vcenterId} onChange={(e) => setVcenterId(e.target.value)}>
            <option value="">すべて（登録済み全体の集約）</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          CPU 閾値（%）
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={metricThresholdCpuInput}
            onChange={(e) =>
              onMetricThresholdInputChange(e.target.value, setMetricThresholdCpuInput, setMetricThresholdCpuPct)
            }
            onBlur={() => setMetricThresholdCpuInput(String(metricThresholdCpuPct))}
            disabled={loading}
          />
        </label>
        <label>
          Memory 閾値（%）
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={metricThresholdMemoryInput}
            onChange={(e) =>
              onMetricThresholdInputChange(e.target.value, setMetricThresholdMemoryInput, setMetricThresholdMemoryPct)
            }
            onBlur={() => setMetricThresholdMemoryInput(String(metricThresholdMemoryPct))}
            disabled={loading}
          />
        </label>
        <label>
          Disk 閾値（%）
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={metricThresholdDiskInput}
            onChange={(e) =>
              onMetricThresholdInputChange(e.target.value, setMetricThresholdDiskInput, setMetricThresholdDiskPct)
            }
            onBlur={() => setMetricThresholdDiskInput(String(metricThresholdDiskPct))}
            disabled={loading}
          />
        </label>
        <label>
          Network 閾値（%）
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={metricThresholdNetworkInput}
            onChange={(e) =>
              onMetricThresholdInputChange(e.target.value, setMetricThresholdNetworkInput, setMetricThresholdNetworkPct)
            }
            onBlur={() => setMetricThresholdNetworkInput(String(metricThresholdNetworkPct))}
            disabled={loading}
          />
        </label>
        <label>
          アラート上位件数
          <input
            type="number"
            inputMode="numeric"
            min={1}
            max={20}
            step={1}
            className="toolbar__input--short"
            value={alertTopNInput}
            onChange={(e) => onAlertTopNInputChange(e.target.value)}
            onBlur={onAlertTopNBlur}
            disabled={loading}
          />
        </label>
        <div className="timeline-panel__metrics" role="group" aria-labelledby="timeline-period-metrics-caption">
          <span id="timeline-period-metrics-caption" className="timeline-panel__metrics-caption">
            含めるメトリクス
          </span>
          <div className="timeline-panel__metrics-options">
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
          </div>
        </div>
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
        <p className="hint toolbar__filters-hint timeline-panel__toolbar-hint">
          閾値（%）はインシデントの判定に使います。含めるメトリクスは、期間内をバケット平均で集約してタイムラインに加えます。
        </p>
      </div>

      {/* 期間は「タイムラインを生成」の直前に置く（生成の直前に確かめる値なので）。 */}
      <section className="timeline-panel__section">
        <ZonedRangeDetails
          displayLabel={rangeDisplayLabel}
          hint="表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。開始・終了の両方を指定してください。日付のみの場合は開始は 0:00・終了は 23:59 です。クイックで直近の範囲を入れられます。"
          value={rangeParts}
          onChange={setRangeParts}
          onQuickPreset={applyRollingPreset}
        />
      </section>
    </>
  )
}
