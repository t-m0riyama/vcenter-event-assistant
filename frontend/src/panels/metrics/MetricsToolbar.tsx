import type { VCenter } from '../../api/schemas'

type MetricsToolbarProps = {
  vcenters: VCenter[]
  vcenterId: string
  setVcenterId: (value: string) => void
  metricKeys: string[]
  metricKey: string
  setMetricKey: (value: string) => void
  chartEventType: string
  setChartEventType: (value: string) => void
  eventTypeOptions: string[]
  loading: boolean
  exportDisabled: boolean
  metricTotal: number | null
  pointsCount: number
  onReload: () => void
  onDownloadSvg: () => void
  onDownloadCsv: () => void
}

/** メトリクスパネルのツールバー（vCenter・系列・export 等）。 */
export function MetricsToolbar({
  vcenters,
  vcenterId,
  setVcenterId,
  metricKeys,
  metricKey,
  setMetricKey,
  chartEventType,
  setChartEventType,
  eventTypeOptions,
  loading,
  exportDisabled,
  metricTotal,
  pointsCount,
  onReload,
  onDownloadSvg,
  onDownloadCsv,
}: MetricsToolbarProps) {
  return (
    <div className="toolbar">
      <label>
        vCenter
        <select value={vcenterId} onChange={(e) => setVcenterId(e.target.value)}>
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
            <option value="">メトリクスキーがありません</option>
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
        onClick={onReload}
      >
        {loading ? '取得中…' : '再取得'}
      </button>
      <button
        type="button"
        className="btn btn--gray"
        disabled={exportDisabled}
        onClick={onDownloadSvg}
      >
        グラフをダウンロード
      </button>
      <button
        type="button"
        className="btn btn--gray"
        disabled={exportDisabled}
        onClick={onDownloadCsv}
      >
        CSV をダウンロード
      </button>
      {metricTotal !== null && !loading && (
        <span className="metric-total">
          条件一致: {metricTotal} 件（表示: {pointsCount} 件まで）
        </span>
      )}
    </div>
  )
}
