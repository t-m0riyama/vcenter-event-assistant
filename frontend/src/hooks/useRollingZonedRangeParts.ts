import { useCallback, useEffect, useRef, useState } from 'react'
import {
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
  const [rollingDurationMs] = useState(METRICS_DEFAULT_ROLLING_DURATION_MS)
  const [rangeParts, setRangePartsState] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(
      METRICS_DEFAULT_ROLLING_DURATION_MS,
      timeZone,
    ),
  )
  const prevTimeZoneRef = useRef<string | null>(null)

  const setRangeParts = useCallback((next: ZonedRangeParts) => {
    setRangeFollowMode('manual')
    setRangePartsState(next)
  }, [])

  useEffect(() => {
    if (prevTimeZoneRef.current === null) {
      prevTimeZoneRef.current = timeZone
      return
    }
    if (prevTimeZoneRef.current === timeZone) return
    prevTimeZoneRef.current = timeZone
    if (rangeFollowMode !== 'rolling') return
    setRangePartsState(
      presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone),
    )
  }, [timeZone, rangeFollowMode, rollingDurationMs])

  return { rangeParts, setRangeParts }
}
