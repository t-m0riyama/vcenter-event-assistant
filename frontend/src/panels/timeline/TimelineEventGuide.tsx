import { useEffect, useState } from 'react'

import type { EventTypeGuideSnippet, TimelineViewItem } from '../../api/schemas'
import { EventTypeGuideBody } from '../../events/EventTypeGuideBody'
import { toErrorMessage } from '../../utils/errors'
import type { GuideLoader } from './eventTypeGuideLoader'

type State =
  | { status: 'loading' }
  | { status: 'ready'; guide: EventTypeGuideSnippet | null }
  | { status: 'error'; message: string }

/**
 * 展開した行に出すイベント種別ガイド。view の応答には載らないので、
 * `GET /api/event-type-guides`（viewer 以上）の一覧から `event_type` で引く。
 */
export function TimelineEventGuide({ item, loader }: { item: TimelineViewItem; loader: GuideLoader }) {
  const eventType = item.ref.event_type ?? ''
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    if (!eventType) return
    let cancelled = false
    loader
      .get(eventType)
      .then((guide) => {
        if (!cancelled) setState({ status: 'ready', guide })
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ status: 'error', message: toErrorMessage(e) })
      })
    return () => {
      cancelled = true
    }
  }, [eventType, loader])

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
