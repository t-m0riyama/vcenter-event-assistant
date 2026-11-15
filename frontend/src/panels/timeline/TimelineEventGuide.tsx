import { useEffect, useState } from 'react'

import { apiGet } from '../../api'
import { normalizeEventListPayload, type EventTypeGuideSnippet, type TimelineViewItem } from '../../api/schemas'
import { parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import { EventTypeGuideBody } from '../../events/EventTypeGuideBody'
import { toErrorMessage } from '../../utils/errors'

/** イベント種別ごとのガイドの取得結果。展開のたびに取り直さないよう、一覧側で共有する。 */
export type GuideCache = Map<string, EventTypeGuideSnippet | null>

type State =
  | { status: 'loading' }
  | { status: 'ready'; guide: EventTypeGuideSnippet | null }
  | { status: 'error'; message: string }

/**
 * イベントのガイドは、イベントタブと同じく `GET /api/events` の `type_guide` で取る
 * （view の応答には載らない）。その行の発生時刻の前後 1 秒で絞り、`event_id` が一致する行を使う。
 */
async function fetchGuide(item: TimelineViewItem): Promise<EventTypeGuideSnippet | null> {
  const eventType = item.ref.event_type
  if (!eventType) return null
  const t = parseApiUtcInstantMs(item.timestamp_utc)
  const q = new URLSearchParams({
    event_type_contains: eventType,
    from: new Date(t - 1000).toISOString(),
    to: new Date(t + 1000).toISOString(),
    limit: '50',
  })
  if (item.vcenter_id) q.set('vcenter_id', item.vcenter_id)
  const { items } = normalizeEventListPayload(await apiGet<unknown>(`/api/events?${q}`))
  const row =
    items.find((e) => e.id === item.ref.event_id) ?? items.find((e) => e.event_type === eventType && e.type_guide)
  return row?.type_guide ?? null
}

/** 展開した行に出すイベント種別ガイド。 */
export function TimelineEventGuide({ item, cache }: { item: TimelineViewItem; cache: GuideCache }) {
  const eventType = item.ref.event_type ?? ''
  const [state, setState] = useState<State>(() =>
    cache.has(eventType) ? { status: 'ready', guide: cache.get(eventType) ?? null } : { status: 'loading' },
  )

  useEffect(() => {
    if (!eventType || cache.has(eventType)) return
    let cancelled = false
    fetchGuide(item)
      .then((guide) => {
        cache.set(eventType, guide)
        if (!cancelled) setState({ status: 'ready', guide })
      })
      .catch((e) => {
        if (!cancelled) setState({ status: 'error', message: toErrorMessage(e) })
      })
    return () => {
      cancelled = true
    }
  }, [item, eventType, cache])

  if (!eventType) return null
  return (
    <div className="timeline-guide">
      <h5>イベント種別ガイド</h5>
      {state.status === 'loading' ? <p className="hint">読み込み中…</p> : null}
      {state.status === 'error' ? <p className="hint">ガイドを取得できませんでした: {state.message}</p> : null}
      {state.status === 'ready' ? (
        state.guide ? (
          <EventTypeGuideBody guide={state.guide} />
        ) : (
          <p className="hint">この種別のガイドは登録されていません。</p>
        )
      ) : null}
    </div>
  )
}
