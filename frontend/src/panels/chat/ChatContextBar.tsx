import { MetricConditionsToolbar } from '../../components/MetricConditionsToolbar'
import type { MetricConditionsToolbarProps } from '../../components/MetricConditionsToolbar'
import { ZonedRangeDetails } from '../../datetime/ZonedRangeDetails'
import type { ZonedRangeParts } from '../../datetime/ZonedRangeFields'

/** 共通の条件（vCenter・閾値・期間メトリクス）に、表示期間を足したもの。 */
type ChatContextBarProps = Omit<MetricConditionsToolbarProps, 'ariaLabel' | 'metricsCaption' | 'hint' | 'children'> & {
  rangeParts: ZonedRangeParts
  setRangeParts: (next: ZonedRangeParts) => void
  applyRollingPreset: (durationMs: number) => void
  rangeDisplayLabel: string
}

/** チャットの集計期間・vCenter・期間メトリクス閾値の入力バー。 */
export function ChatContextBar(props: ChatContextBarProps) {
  const { rangeParts, setRangeParts, applyRollingPreset, rangeDisplayLabel } = props
  return (
    <>
      <section className="chat-panel__section">
        <ZonedRangeDetails
          displayLabel={rangeDisplayLabel}
          hint="表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。開始・終了の両方を指定してください。日付のみの場合は開始は 0:00・終了は 23:59 です。クイックで直近の範囲を入れられます。"
          value={rangeParts}
          onChange={setRangeParts}
          onQuickPreset={applyRollingPreset}
        />
      </section>

      <section className="chat-panel__section">
        <MetricConditionsToolbar
          {...props}
          ariaLabel="チャットの条件"
          metricsCaption="LLM に含めるメトリクス"
          hint="閾値（%）はインシデントの判定に使います。含めるメトリクスは、期間内をバケット平均で LLM に送ります（DB への問い合わせが増えます）。"
        />
      </section>
    </>
  )
}
