import { useEffect, useId, useState } from 'react'

import { ApiError } from '../../api'
import { getInventoryConfigDiffs, type InventoryConfigDiffQuery } from '../../api/inventory'
import type { InventoryConfigDiffResponse } from '../../api/schemas'
import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import { TimelineConfigDiffList } from './TimelineConfigDiffList'

type DiffResult = Pick<InventoryConfigDiffQuery, 'from' | 'to'> & ({ data: InventoryConfigDiffResponse } | { error: string })

function statusMessage(result: DiffResult | null): string | null {
  if (!result) return '構成の差分を読み込み中…'
  if ('error' in result) return result.error
  const { status, total } = result.data
  if (status === 'disabled') return '構成の差分の記録は無効です'
  if (status === 'not_recorded') return 'まだ構成を読み取っていません'
  return total === 0 ? 'この期間に観測した構成の差分はありません' : null
}

export function TimelineConfigDiffSection({ query, timeZone, showingSaved }: {
  query: InventoryConfigDiffQuery
  timeZone: string
  showingSaved: boolean
}) {
  const { vcenter_id, entity_moid, from, to } = query
  const [result, setResult] = useState<DiffResult | null>(null)
  const headingId = useId()

  useEffect(() => {
    const controller = new AbortController()
    const { signal } = controller
    // StrictMode の片付けが先に走った要求も送らない。
    void Promise.resolve().then(async () => {
      if (signal.aborted) return
      try {
        const response = await getInventoryConfigDiffs({ vcenter_id, entity_moid, from, to }, signal)
        if (!signal.aborted) setResult({ from, to, data: response })
      } catch (error) {
        if (!signal.aborted) {
          setResult({ from, to, error: error instanceof ApiError && error.status === 404
            ? 'この vCenter は登録されていません。'
            : '構成の差分を読み込めませんでした。' })
        }
      }
    })
    return () => controller.abort()
  }, [vcenter_id, entity_moid, from, to])

  // 同じ対象の期間を取り直す間は、直前の結果とその期間を使う。
  const updating = result && (result.from !== from || result.to !== to)
  const displayed = result && 'data' in result ? result : null
  const data = displayed?.data
  const recordedSince = data?.recorded_since
  const items = data ? [...data.items].sort((a, b) => {
    const timeOrder = parseApiUtcInstantMs(b.observed_at) - parseApiUtcInstantMs(a.observed_at)
    // API は UTC で返す。ミリ秒が同じ場合は小数秒の残りも比べる。
    const fractionOrder = Number(b.observed_at.match(/\.\d+/)?.[0] ?? 0) - Number(a.observed_at.match(/\.\d+/)?.[0] ?? 0)
    return timeOrder || fractionOrder || b.id - a.id
  }) : []

  return (
    <section className="timeline-config-diffs" aria-labelledby={headingId}>
      <h3 id={headingId} className="timeline-section-title">構成の差分</h3>
      <div className="timeline-config-diffs__content">
        <p className="hint timeline-config-diffs__status" role="status">{updating ? '構成の差分を更新中…' : statusMessage(result)}</p>
        {data && displayed && (
          <>
            <p className="hint">{data.target.name}{showingSaved && '（現在残っている差分）'}</p>
            {data.status === 'not_recorded' && (
              <p className="hint"><a href="#/settings/vcenters">設定の vCenter 一覧</a>で収集状態を確認できます。</p>
            )}
            {data.status === 'ok' && data.total === 0 && recordedSince &&
              parseApiUtcInstantMs(displayed.from) < parseApiUtcInstantMs(recordedSince) && (
                <p className="hint">記録は <time dateTime={recordedSince}>{formatIsoInTimeZone(recordedSince, timeZone)}</time> から</p>
              )}
            <TimelineConfigDiffList items={items} timeZone={timeZone} firstSuccessAt={data.first_success_at} />
            {items.length < data.total && <p className="hint">{data.total} 件のうち新しい {items.length} 件を出しています</p>}
            {items.length > 0 && (
              <p className="hint">変化の幅は、前の値を最後に確かめた時刻と、新しい値の観測の時刻で決まります。</p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
