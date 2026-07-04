import { ZonedRangeFields, type ZonedRangeParts } from '../../datetime/ZonedRangeFields'

type MetricsRangeFieldsProps = {
  graphRangeDisplayLabel: string
  autoRefreshEnabled: boolean
  setAutoRefreshEnabled: (enabled: boolean) => void
  autoRefreshIntervalMinutes: number
  rangeParts: ZonedRangeParts
  onGraphRangeFieldsChange: (next: ZonedRangeParts) => void
  applyRollingPreset: (durationMs: number) => void
}

/** メトリクスグラフの期間入力（ローリング / 手入力）。 */
export function MetricsRangeFields({
  graphRangeDisplayLabel,
  autoRefreshEnabled,
  setAutoRefreshEnabled,
  autoRefreshIntervalMinutes,
  rangeParts,
  onGraphRangeFieldsChange,
  applyRollingPreset,
}: MetricsRangeFieldsProps) {
  return (
    <details className="toolbar__filters-details metrics-panel__range-details">
      <summary className="toolbar__filters-summary">
        <span className="toolbar__filters-summary__title">表示期間</span>
        <span className="toolbar__filters-summary__preview">{graphRangeDisplayLabel}</span>
      </summary>
      <p className="hint toolbar__filters-hint">
        表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。開始・終了は両方指定するか、すべて空にしてください。日付のみの場合は開始は
        0:00・終了は 23:59 です。期間を指定するとメトリクスは最大 10000
        点まで取得し、イベント件数オーバーレイも同じ区間で集計します。
      </p>
      <div className="metrics-panel__range-auto-refresh">
        <label className="tz-select tz-select--inline">
          <input
            type="checkbox"
            checked={autoRefreshEnabled}
            onChange={(e) => setAutoRefreshEnabled(e.target.checked)}
            aria-label="自動更新"
          />
          自動更新（{autoRefreshIntervalMinutes} 分ごと）
        </label>
      </div>
      <ZonedRangeFields
        value={rangeParts}
        onChange={onGraphRangeFieldsChange}
        onQuickPreset={applyRollingPreset}
      />
    </details>
  )
}
