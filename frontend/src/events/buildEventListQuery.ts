/**
 * UI のフィルタ入力（`GET /api/events` と共通）。
 */
export type EventListFilterFields = {
  readonly minScore: string
  readonly filterEventType: string
  readonly filterSeverity: string
  readonly filterMessage: string
  readonly filterComment: string
}

export type EventListUtcRange = {
  readonly from?: string
  readonly to?: string
}

/**
 * `limit` / `offset` に加え、スコア・テキスト絞り込みと UTC の `from` / `to` を付与する。
 */
export function buildEventListSearchParams(args: {
  readonly limit: number
  readonly offset: number
  readonly filters: EventListFilterFields
  readonly range: EventListUtcRange
}): URLSearchParams {
  const q = new URLSearchParams({
    limit: String(args.limit),
    offset: String(args.offset),
  })
  const { minScore, filterEventType, filterSeverity, filterMessage, filterComment } =
    args.filters
  if (minScore) q.set('min_score', minScore)
  const et = filterEventType.trim()
  if (et) q.set('event_type_contains', et)
  const sv = filterSeverity.trim()
  if (sv) q.set('severity_contains', sv)
  const msg = filterMessage.trim()
  if (msg) q.set('message_contains', msg)
  const cm = filterComment.trim()
  if (cm) q.set('comment_contains', cm)
  if (args.range.from) q.set('from', args.range.from)
  if (args.range.to) q.set('to', args.range.to)
  return q
}
