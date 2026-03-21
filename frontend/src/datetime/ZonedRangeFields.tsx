import { useTimeZone } from './useTimeZone'
import {
  presetRelativeRangeWallParts,
  type ZonedRangeParts,
} from './zonedRangeParts'

export type { ZonedRangeParts }

type ZonedRangeFieldsProps = {
  /** Current four field values. */
  value: ZonedRangeParts
  onChange: (next: ZonedRangeParts) => void
}

/**
 * Native date/time pickers for a wall-clock range in the app display time zone.
 * Values are combined server-side with {@link zonedRangePartsToCombinedInputs}.
 */
export function ZonedRangeFields({ value, onChange }: ZonedRangeFieldsProps) {
  const { timeZone } = useTimeZone()

  const setPart = (patch: Partial<ZonedRangeParts>) => {
    onChange({ ...value, ...patch })
  }

  const applyPreset = (durationMs: number) => {
    onChange(presetRelativeRangeWallParts(durationMs, timeZone))
  }

  return (
    <div className="zoned-range-fields">
      <div className="toolbar__filters zoned-range-fields__row" aria-label="表示期間">
        <label className="zoned-range-fields__date">
          開始日
          <input
            type="date"
            value={value.fromDate}
            onChange={(e) => setPart({ fromDate: e.target.value })}
          />
        </label>
        <label className="zoned-range-fields__time">
          開始時刻
          <input
            type="time"
            step={60}
            value={value.fromTime}
            onChange={(e) => setPart({ fromTime: e.target.value })}
          />
        </label>
        <label className="zoned-range-fields__date">
          終了日
          <input
            type="date"
            value={value.toDate}
            onChange={(e) => setPart({ toDate: e.target.value })}
          />
        </label>
        <label className="zoned-range-fields__time">
          終了時刻
          <input
            type="time"
            step={60}
            value={value.toTime}
            onChange={(e) => setPart({ toTime: e.target.value })}
          />
        </label>
      </div>
      <div className="zoned-range-fields__presets">
        <span className="zoned-range-fields__presets-label">クイック:</span>
        <button type="button" className="btn btn--gray" onClick={() => applyPreset(86400000)}>
          過去 24 時間
        </button>
        <button type="button" className="btn btn--gray" onClick={() => applyPreset(2 * 86400000)}>
          過去 2 日
        </button>
        <button type="button" className="btn btn--gray" onClick={() => applyPreset(7 * 86400000)}>
          過去 7 日
        </button>
        <button type="button" className="btn btn--gray" onClick={() => applyPreset(30 * 86400000)}>
          過去 30 日
        </button>
      </div>
    </div>
  )
}
