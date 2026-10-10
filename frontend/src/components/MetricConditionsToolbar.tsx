import type { ReactNode } from 'react'
import { useId } from 'react'
import type { VCenter } from '../api/schemas'

export type MetricConditionsToolbarProps = {
  /** ツールバー全体の aria-label。 */
  ariaLabel: string
  /** 期間メトリクスのチェックボックスの見出し。 */
  metricsCaption: string
  /** ツールバーの下に 1 行で出す説明。 */
  hint: ReactNode
  /** 期間メトリクスの後ろに置くもの（タイムラインのアラート上位件数・表示順など）。 */
  children?: ReactNode
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
  onMetricThresholdInputChange: (
    rawValue: string,
    setInput: (value: string) => void,
    setValue: (value: number) => void,
  ) => void
}

/**
 * vCenter・メトリクスの閾値・期間メトリクスを、イベントやログと同じツールバーの形
 * （ラベルが上、入力欄が下で横に並べる）で出す。チャットとタイムラインで共通。
 */
export function MetricConditionsToolbar(props: MetricConditionsToolbarProps) {
  const { ariaLabel, metricsCaption, hint, children, vcenters, vcenterId, setVcenterId, loading } = props
  const captionId = useId()

  const thresholds = [
    ['CPU 閾値（%）', props.metricThresholdCpuInput, props.metricThresholdCpuPct, props.setMetricThresholdCpuInput, props.setMetricThresholdCpuPct],
    ['Memory 閾値（%）', props.metricThresholdMemoryInput, props.metricThresholdMemoryPct, props.setMetricThresholdMemoryInput, props.setMetricThresholdMemoryPct],
    ['Disk 閾値（%）', props.metricThresholdDiskInput, props.metricThresholdDiskPct, props.setMetricThresholdDiskInput, props.setMetricThresholdDiskPct],
    ['Network 閾値（%）', props.metricThresholdNetworkInput, props.metricThresholdNetworkPct, props.setMetricThresholdNetworkInput, props.setMetricThresholdNetworkPct],
  ] as const

  const metrics = [
    ['CPU 使用率', props.includePeriodMetricsCpu, props.setIncludePeriodMetricsCpu],
    ['メモリ使用率', props.includePeriodMetricsMemory, props.setIncludePeriodMetricsMemory],
    ['ディスク IO', props.includePeriodMetricsDiskIo, props.setIncludePeriodMetricsDiskIo],
    ['ネットワーク IO', props.includePeriodMetricsNetworkIo, props.setIncludePeriodMetricsNetworkIo],
  ] as const

  return (
    <div className="toolbar" aria-label={ariaLabel}>
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
      {thresholds.map(([label, input, pct, setInput, setPct]) => (
        <label key={label}>
          {label}
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={input}
            onChange={(e) => props.onMetricThresholdInputChange(e.target.value, setInput, setPct)}
            onBlur={() => setInput(String(pct))}
            disabled={loading}
          />
        </label>
      ))}
      <div className="toolbar__checks" role="group" aria-labelledby={captionId}>
        <span id={captionId}>{metricsCaption}</span>
        <div className="toolbar__checks-options">
          {metrics.map(([label, checked, setChecked]) => (
            <label key={label} className="toolbar__check">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
                disabled={loading}
              />
              {label}
            </label>
          ))}
        </div>
      </div>
      {children}
      <p className="hint toolbar__note">{hint}</p>
    </div>
  )
}
