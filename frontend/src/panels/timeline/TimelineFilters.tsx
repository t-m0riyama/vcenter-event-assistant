import type { MetricConditionsToolbarProps } from '../../components/MetricConditionsToolbar'
import { MetricConditionsToolbar } from '../../components/MetricConditionsToolbar'
import { ZonedRangeDetails } from '../../datetime/ZonedRangeDetails'
import type { ZonedRangeParts } from '../../datetime/ZonedRangeFields'

/** 共通の条件（vCenter・閾値・期間メトリクス）に、表示期間とタイムライン固有の項目を足したもの。 */
type TimelineFiltersProps = Omit<MetricConditionsToolbarProps, 'ariaLabel' | 'metricsCaption' | 'hint' | 'children'> & {
  rangeParts: ZonedRangeParts
  setRangeParts: (next: ZonedRangeParts) => void
  applyRollingPreset: (durationMs: number) => void
  rangeDisplayLabel: string
  alertTopNInput: string
  alertTopN: number
  setAlertTopNInput: (value: string) => void
  setAlertTopN: (value: number) => void
  sortOrder: 'asc' | 'desc'
  setSortOrder: (value: 'asc' | 'desc' | ((current: 'asc' | 'desc') => 'asc' | 'desc')) => void
  onAlertTopNInputChange: (rawValue: string) => void
  onAlertTopNBlur: () => void
}

/** タイムライン生成条件（期間・vCenter・メトリクス閾値等）の入力フォーム。 */
export function TimelineFilters(props: TimelineFiltersProps) {
  const {
    rangeParts,
    setRangeParts,
    applyRollingPreset,
    rangeDisplayLabel,
    loading,
    alertTopNInput,
    sortOrder,
    setSortOrder,
    onAlertTopNInputChange,
    onAlertTopNBlur,
  } = props
  return (
    <>
      <MetricConditionsToolbar
        {...props}
        ariaLabel="タイムラインの条件"
        metricsCaption="含めるメトリクス"
        hint="閾値（%）はインシデントの判定に使います。含めるメトリクスは、期間内をバケット平均で集約してタイムラインに加えます。"
      >
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
      </MetricConditionsToolbar>

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
