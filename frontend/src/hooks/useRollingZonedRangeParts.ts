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

  /**
   * 保存しておいた期間を戻す。``rollingDurationMs`` があれば「直近 N」として戻す（null は手入力）。
   * 期間の値は保存したものを使い、今の時刻から計算し直さない。
   */
  const restoreRange = useCallback((parts: ZonedRangeParts, savedRollingDurationMs: number | null) => {
    if (savedRollingDurationMs === null) {
      setRangeFollowMode('manual')
    } else {
      setRangeFollowMode('rolling')
      setRollingDurationMs(savedRollingDurationMs)
    }
    setRangePartsState(parts)
  }, [])

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

  return {
    rangeParts,
    setRangeParts,
    applyRollingPreset,
    restoreRange,
    rangeDisplayLabel,
    /** 「直近 N」のときの N（ミリ秒）。手入力のときは null。保存して {@link restoreRange} に渡す。 */
    activeRollingDurationMs: rangeFollowMode === 'rolling' ? rollingDurationMs : null,
  }
}
