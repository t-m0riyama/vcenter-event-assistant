import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { resolveMetricsReplay, type MetricsReplayInput } from './metricsReplay'
import {
  resolveMetricsGraphRange,
  summarizeGraphRangePreview,
} from '../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  formatRollingDurationLabel,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsFromUtcIsoEndpoints,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'

/** グラフの表示期間がクイックプリセットに追従するか、手入力固定か。 */
export type GraphRangeFollowMode = 'rolling' | 'manual'

export type { MetricsSnapshotReplayInput, MetricsReplayInput, MetricsFocus } from './metricsReplay'

type UseGraphRangeStateOptions = {
  /** ローリング期間の TZ 追随で range が更新されたとき */
  onRollingRangeInvalidated?: () => void
}

/** メトリクスグラフの表示期間・ローリング追従状態を管理する。 */
export function useGraphRangeState(
  timeZone: string,
  snapshotReplay?: MetricsReplayInput | null,
  options?: UseGraphRangeStateOptions,
) {
  const [graphRangeFollowMode, setGraphRangeFollowMode] =
    useState<GraphRangeFollowMode>('rolling')
  const [rollingDurationMs, setRollingDurationMs] = useState(
    METRICS_DEFAULT_ROLLING_DURATION_MS,
  )
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(
      METRICS_DEFAULT_ROLLING_DURATION_MS,
      timeZone,
    ),
  )
  const prevTimeZoneRef = useRef<string | null>(null)
  const [previousTimeZone, setPreviousTimeZone] = useState(timeZone)
  const replay = resolveMetricsReplay(snapshotReplay)
  const snapshotItem = replay?.source
  const snapshotNonce = replay?.nonce
  const [appliedSnapshot, setAppliedSnapshot] = useState<{
    item: object | undefined
    nonce: number | undefined
    timeZone: string
  }>({ item: undefined, nonce: undefined, timeZone })
  const onRollingRangeInvalidated = options?.onRollingRangeInvalidated

  const { rangeFromInput, rangeToInput } = useMemo(
    () => zonedRangePartsToCombinedInputs(rangeParts),
    [rangeParts],
  )

  if (previousTimeZone !== timeZone) {
    setPreviousTimeZone(timeZone)
    if (graphRangeFollowMode === 'rolling') {
      setRangeParts(presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone))
    }
  }

  if (
    appliedSnapshot.item !== snapshotItem ||
    appliedSnapshot.nonce !== snapshotNonce ||
    appliedSnapshot.timeZone !== timeZone
  ) {
    setAppliedSnapshot({ item: snapshotItem, nonce: snapshotNonce, timeZone })
    if (replay) {
      setGraphRangeFollowMode('manual')
      setRangeParts(zonedRangePartsFromUtcIsoEndpoints(replay.from, replay.to, timeZone))
    }
  }

  const onGraphRangeFieldsChange = useCallback((next: ZonedRangeParts) => {
    setGraphRangeFollowMode('manual')
    setRangeParts(next)
  }, [])

  const applyRollingPreset = useCallback(
    (durationMs: number) => {
      setGraphRangeFollowMode('rolling')
      setRollingDurationMs(durationMs)
      setRangeParts(presetRelativeRangeWallPartsWithUtcFallback(durationMs, timeZone))
    },
    [timeZone],
  )

  useEffect(() => {
    if (prevTimeZoneRef.current === null) {
      prevTimeZoneRef.current = timeZone
      return
    }
    if (prevTimeZoneRef.current === timeZone) return
    prevTimeZoneRef.current = timeZone
    if (graphRangeFollowMode !== 'rolling') return
    onRollingRangeInvalidated?.()
  }, [
    timeZone,
    graphRangeFollowMode,
    onRollingRangeInvalidated,
  ])

  const graphRangeForOverlay = useMemo(
    () => resolveMetricsGraphRange(rangeFromInput, rangeToInput, timeZone),
    [rangeFromInput, rangeToInput, timeZone],
  )

  const graphRangeDisplayLabel = useMemo(() => {
    if (graphRangeFollowMode === 'rolling') {
      return formatRollingDurationLabel(rollingDurationMs)
    }
    return summarizeGraphRangePreview(rangeParts)
  }, [graphRangeFollowMode, rollingDurationMs, rangeParts])

  const refreshRollingRange = useCallback(() => {
    setRangeParts(
      presetRelativeRangeWallPartsWithUtcFallback(rollingDurationMs, timeZone),
    )
  }, [rollingDurationMs, timeZone])

  return {
    graphRangeFollowMode,
    rollingDurationMs,
    rangeParts,
    rangeFromInput,
    rangeToInput,
    onGraphRangeFieldsChange,
    applyRollingPreset,
    graphRangeForOverlay,
    graphRangeDisplayLabel,
    refreshRollingRange,
  }
}
