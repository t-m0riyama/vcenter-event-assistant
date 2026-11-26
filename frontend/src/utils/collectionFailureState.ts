import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'

export type CollectionFailureState = 'current' | 'past' | 'unknown'

export function getCollectionFailureState(
  lastSuccessAt: string | null,
  lastFailureAt: string | null,
): CollectionFailureState {
  if (!lastFailureAt) return 'unknown'
  const failureMs = parseApiUtcInstantMs(lastFailureAt)
  if (Number.isNaN(failureMs)) return 'unknown'
  if (!lastSuccessAt) return 'current'

  const differenceMs = failureMs - parseApiUtcInstantMs(lastSuccessAt)
  if (Number.isNaN(differenceMs)) return 'unknown'
  // API の小数秒はミリ秒より細かいことがある。
  const difference = differenceMs || (
    Number(lastFailureAt.match(/\.\d+/)?.[0] ?? 0) - Number(lastSuccessAt.match(/\.\d+/)?.[0] ?? 0)
  )
  if (difference > 0) return 'current'
  if (difference < 0) return 'past'
  return 'unknown'
}
