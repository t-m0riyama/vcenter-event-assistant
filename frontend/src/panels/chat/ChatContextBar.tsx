import type { VCenter } from '../../api/schemas'
import { ZonedRangeFields, type ZonedRangeParts } from '../../datetime/ZonedRangeFields'

type MetricThresholdFieldProps = {
  label: string
  inputValue: string
  loading: boolean
  onInputChange: (rawValue: string) => void
  onBlurSync: () => void
}

function MetricThresholdField({
  label,
  inputValue,
  loading,
  onInputChange,
  onBlurSync,
}: MetricThresholdFieldProps) {
  return (
    <label className="chat-panel__threshold-field">
      {label}
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        value={inputValue}
        onChange={(e) => onInputChange(e.target.value)}
        onBlur={onBlurSync}
        disabled={loading}
      />
    </label>
  )
}

type ChatContextBarProps = {
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
  onMetricThresholdInputChange: (
    rawValue: string,
    setInput: (value: string) => void,
    setValue: (value: number) => void,
  ) => void
}

export function ChatContextBar({
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
  onMetricThresholdInputChange,
}: ChatContextBarProps) {
  return (
    <>
      <section className="chat-panel__section" aria-label="集計期間">
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </section>

      <section className="chat-panel__section" aria-label="vCenter">
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

      <section className="chat-panel__section" aria-label="期間メトリクス">
        <p className="hint chat-panel__metrics-hint">
          LLM に含めるメトリクス（期間内をバケット平均で送る・追加 DB クエリあり）
        </p>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsCpu}
            onChange={(e) => setIncludePeriodMetricsCpu(e.target.checked)}
            disabled={loading}
          />
          CPU 使用率
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsMemory}
            onChange={(e) => setIncludePeriodMetricsMemory(e.target.checked)}
            disabled={loading}
          />
          メモリ使用率
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsDiskIo}
            onChange={(e) => setIncludePeriodMetricsDiskIo(e.target.checked)}
            disabled={loading}
          />
          ディスク IO
        </label>
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includePeriodMetricsNetworkIo}
            onChange={(e) => setIncludePeriodMetricsNetworkIo(e.target.checked)}
            disabled={loading}
          />
          ネットワーク IO
        </label>
      </section>

      <section className="chat-panel__section" aria-label="メトリクス閾値">
        <p className="hint chat-panel__metrics-hint">インシデント判定に使う閾値（%）</p>
        <div className="chat-panel__threshold-grid">
          <MetricThresholdField
            label="CPU 閾値（%）"
            inputValue={metricThresholdCpuInput}
            loading={loading}
            onInputChange={(raw) =>
              onMetricThresholdInputChange(raw, setMetricThresholdCpuInput, setMetricThresholdCpuPct)
            }
            onBlurSync={() => setMetricThresholdCpuInput(String(metricThresholdCpuPct))}
          />
          <MetricThresholdField
            label="Memory 閾値（%）"
            inputValue={metricThresholdMemoryInput}
            loading={loading}
            onInputChange={(raw) =>
              onMetricThresholdInputChange(
                raw,
                setMetricThresholdMemoryInput,
                setMetricThresholdMemoryPct,
              )
            }
            onBlurSync={() => setMetricThresholdMemoryInput(String(metricThresholdMemoryPct))}
          />
          <MetricThresholdField
            label="Disk 閾値（%）"
            inputValue={metricThresholdDiskInput}
            loading={loading}
            onInputChange={(raw) =>
              onMetricThresholdInputChange(raw, setMetricThresholdDiskInput, setMetricThresholdDiskPct)
            }
            onBlurSync={() => setMetricThresholdDiskInput(String(metricThresholdDiskPct))}
          />
          <MetricThresholdField
            label="Network 閾値（%）"
            inputValue={metricThresholdNetworkInput}
            loading={loading}
            onInputChange={(raw) =>
              onMetricThresholdInputChange(
                raw,
                setMetricThresholdNetworkInput,
                setMetricThresholdNetworkPct,
              )
            }
            onBlurSync={() => setMetricThresholdNetworkInput(String(metricThresholdNetworkPct))}
          />
        </div>
      </section>
    </>
  )
}
