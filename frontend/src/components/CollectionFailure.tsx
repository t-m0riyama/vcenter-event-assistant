import type { ReactNode } from 'react'

import { formatIsoInTimeZone } from '../datetime/formatIsoInTimeZone'
import { collectionErrorMessage } from '../utils/collectionErrorMessage'
import type { CollectionFailureState } from '../utils/collectionFailureState'
import './CollectionFailure.css'

export function CurrentCollectionFailure() {
  return <strong className="collection-failure__current">失敗中</strong>
}

type Props = {
  readonly state: CollectionFailureState
  readonly targetName: string
  readonly lastSuccessAt: string | null
  readonly lastFailureAt: string | null
  readonly error: string | null
  readonly timeZone: string
  readonly showFailureTime?: boolean
  readonly hideCurrentLabel?: boolean
  readonly emptyContent?: ReactNode
}

export function CollectionFailure({
  state, targetName, lastSuccessAt, lastFailureAt, error, timeZone, showFailureTime, hideCurrentLabel, emptyContent = null,
}: Props) {
  const hasFailureTime = showFailureTime && lastFailureAt
  if (state === 'unknown' && !error && !hasFailureTime) return emptyContent

  const recovered = state === 'past'
  const showTime = (at: string) => <time dateTime={at}>{formatIsoInTimeZone(at, timeZone)}</time>

  return (
    <div className={recovered ? 'collection-failure collection-failure--past' : 'collection-failure'}>
      {state === 'current' && !hideCurrentLabel && <CurrentCollectionFailure />}
      {recovered && <div>過去の失敗</div>}
      {showFailureTime && <div>最後の失敗 {lastFailureAt ? showTime(lastFailureAt) : '—'}</div>}
      {recovered && lastSuccessAt && <div>この後、{showTime(lastSuccessAt)} に成功しています</div>}
      {error && (
        <>
          <div>{collectionErrorMessage(error)}</div>
          <details>
            <summary aria-label={`詳細（${targetName} のエラー）`}>詳細</summary>
            <div className="collection-failure__record">{error}</div>
          </details>
        </>
      )}
    </div>
  )
}
