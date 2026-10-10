import { useCallback, useMemo, useState } from 'react'
import { summarizeGraphRangePreview } from '../datetime/graphRange'
import {
  formatRollingDurationLabel,
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'

type RangeFollowMode = 'rolling' | 'manual'

/**
 * 表示 TZ 上のローリング期間（既定は直近24時間）を保持する。
 * 手入力後は manual となり、TZ 変更では上書きしない（グラフタブの rolling 追随と同じ）。
 */
export function useRollingZonedRangeParts(timeZone: string) {
  const [rangeFollowMode, setRangeFollowMode] = useState<RangeFollowMode>('rolling')
  const [rollingDurationMs, setRollingDurationMs] = useState(METRICS_DEFAULT_ROLLING_DURATION_MS)
  const [rangeParts, setRangePartsState] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(
      METRICS_DEFAULT_ROLLING_DURATION_MS,
      timeZone,
    ),
  )
  const [previousTimeZone, setPreviousTimeZone] = useState(timeZone)

  const setRangeParts = useCallback((next: ZonedRangeParts) => {
    setRangeFollowMode('manual')
    setRangePartsState(next)
  }, [])

  /** クイックの「過去 N」。ローリングに戻し、要約も「直近 N」にする。 */
  const applyRollingPreset = useCallback(
    (durationMs: number) => {
      setRangeFollowMode('rolling')
      setRollingDurationMs(durationMs)
      setRangePartsState(presetRelativeRangeWallPartsWithUtcFallback(durationMs, timeZone))
    },
    [timeZone],
  )

  /** 折りたたんだ「表示期間」の要約（グラフタブと同じ表記）。 */
  const rangeDisplayLabel = useMemo(
    () =>
      rangeFollowMode === 'rolling'
        ? formatRollingDurationLabel(rollingDurationMs)
        : summarizeGraphRangePreview(rangeParts),
    [rangeFollowMode, rollingDurationMs, rangeParts],
  )

  if (previousTimeZone !== timeZone) {
    setPreviousTimeZone(timeZone)
    if (rangeFollowMode === 'rolling') {
      setRangePartsState(
        presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone),
      )
    }
  }

  return { rangeParts, setRangeParts, applyRollingPreset, rangeDisplayLabel }
}
