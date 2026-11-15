import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import type {
  IncidentTimelineViewRequest,
  TimelineOverviewBucket,
  TimelineViewItem,
} from '../../api/schemas'
import { correlationHash } from '../../routing/correlationRange'
import type { TimelineConditions, TimelineRange } from '../../routing/timelineHash'

/** UTC の期間（ISO 8601）。 */
export type ResolvedRange = { readonly from: string; readonly to: string }

const MAX_SPAN_MS = 90 * 86_400_000
/** イベント・ログで開くときに行の時刻の前後に取る幅（ミリ秒）。 */
export const CORRELATION_HALF_WIDTH_MS = 300_000

function iso(ms: number): string {
  return new Date(ms).toISOString()
}

/** 期間を UTC の `from` / `to` にする。直近 N 時間は `nowMs` を終わりにする。 */
export function resolveTimelineRange(range: TimelineRange, nowMs: number): ResolvedRange {
  if (range.mode === 'fixed') return { from: range.from, to: range.to }
  return { from: iso(nowMs - range.durationMs), to: iso(nowMs) }
}

/** API が受け付けない期間（逆順・同じ秒・90 日超）の理由。問題なければ null。 */
export function validateResolvedRange(range: ResolvedRange): string | null {
  const from = parseApiUtcInstantMs(range.from)
  const to = parseApiUtcInstantMs(range.to)
  if (!Number.isFinite(from) || !Number.isFinite(to)) return '期間の開始と終了を指定してください。'
  if (Math.floor(from / 1000) >= Math.floor(to / 1000)) return '開始は終了より前の時刻にしてください。'
  if (to - from > MAX_SPAN_MS) return '期間は 90 日以内にしてください。'
  return null
}

/** 棒 1 本ぶんの範囲。最後の棒は期間の終わりで切れるので、終わりは `min(開始 + バケット幅, to)`。 */
export function bucketRange(bucketStartUtc: string, bucketSeconds: number, toUtc: string): ResolvedRange {
  const start = parseApiUtcInstantMs(bucketStartUtc)
  const end = Math.min(start + bucketSeconds * 1000, parseApiUtcInstantMs(toUtc))
  return { from: iso(start), to: iso(end) }
}

/** ドラッグで選んだ棒（始点と終点、順不同）の範囲。 */
export function dragRange(
  startBucketUtc: string,
  endBucketUtc: string,
  bucketSeconds: number,
  toUtc: string,
): ResolvedRange {
  const a = parseApiUtcInstantMs(startBucketUtc)
  const b = parseApiUtcInstantMs(endBucketUtc)
  const first = a <= b ? startBucketUtc : endBucketUtc
  const last = a <= b ? endBucketUtc : startBucketUtc
  return {
    from: bucketRange(first, bucketSeconds, toUtc).from,
    to: bucketRange(last, bucketSeconds, toUtc).to,
  }
}

/** 起点を中心にした前後 `halfWidthMs` の範囲。 */
export function anchorWindow(anchorUtc: string, halfWidthMs: number): ResolvedRange {
  const t = parseApiUtcInstantMs(anchorUtc)
  return { from: iso(t - halfWidthMs), to: iso(t + halfWidthMs) }
}

/** 期間を 2 倍に広げる（90 日まで）。直近 N 時間は終わりを今に保ち、固定は前後に半分ずつ足す。 */
export function widenRange(current: ResolvedRange, range: TimelineRange): ResolvedRange {
  const from = parseApiUtcInstantMs(current.from)
  const to = parseApiUtcInstantMs(current.to)
  const span = to - from
  const target = Math.min(span * 2, MAX_SPAN_MS)
  if (range.mode === 'rolling') return { from: iso(to - target), to: iso(to) }
  const pad = (target - span) / 2
  return { from: iso(from - pad), to: iso(to + pad) }
}

/** 起点に最も近い行の id（区間のある行は区間までの距離）。起点が無い・行が無いときは null。 */
export function nearestItemIdToAnchor(items: readonly TimelineViewItem[], anchorUtc: string | null): string | null {
  if (!anchorUtc || items.length === 0) return null
  const anchor = parseApiUtcInstantMs(anchorUtc)
  let best: { id: string; distance: number } | null = null
  for (const item of items) {
    const start = parseApiUtcInstantMs(item.timestamp_utc)
    const end = item.end_utc ? parseApiUtcInstantMs(item.end_utc) : start
    const distance = anchor < start ? start - anchor : anchor > end ? anchor - end : 0
    if (best === null || distance < best.distance) best = { id: item.id, distance }
  }
  return best?.id ?? null
}

/** 起点を含む棒（開始が起点以前で最も遅いもの）の開始時刻。範囲外なら null。 */
export function bucketStartContaining(
  buckets: readonly TimelineOverviewBucket[],
  bucketSeconds: number,
  anchorUtc: string | null,
): string | null {
  if (!anchorUtc) return null
  const t = parseApiUtcInstantMs(anchorUtc)
  for (const b of buckets) {
    const start = parseApiUtcInstantMs(b.bucket_start_utc)
    if (t >= start && t < start + bucketSeconds * 1000) return b.bucket_start_utc
  }
  return null
}

export type TimelineSortOrder = 'asc' | 'desc'

/** API は古い順で返す。新しい順のときだけ反転する。 */
export function sortTimelineItems(items: readonly TimelineViewItem[], order: TimelineSortOrder): TimelineViewItem[] {
  return order === 'asc' ? [...items] : [...items].reverse()
}

/** `POST /api/incident-timeline/view` の本文を組み立てる。 */
export function buildViewRequest(conditions: TimelineConditions, range: ResolvedRange): IncidentTimelineViewRequest {
  const body: IncidentTimelineViewRequest = {
    from: range.from,
    to: range.to,
    min_score: conditions.minScore,
    sources: [...conditions.sources],
  }
  if (conditions.anchor) body.anchor = conditions.anchor
  if (conditions.vcenterId) body.vcenter_id = conditions.vcenterId
  if (conditions.entity) body.entity = conditions.entity
  return body
}

/** 行の時刻の前後 5 分と vCenter をイベント・ログのタブへ渡すハッシュ。vCenter が無い行は null。 */
export function correlationHashForItem(tab: 'events' | 'logs', item: TimelineViewItem): string | null {
  if (!item.vcenter_id) return null
  const t = parseApiUtcInstantMs(item.timestamp_utc)
  if (!Number.isFinite(t)) return null
  return correlationHash(tab, {
    vcenterId: item.vcenter_id,
    from: iso(t - CORRELATION_HALF_WIDTH_MS),
    to: iso(t + CORRELATION_HALF_WIDTH_MS),
  })
}

/** 棒のツールチップに出す範囲。最後の棒は期間の終わりで切れるので `min(開始 + バケット幅, to)`。 */
export function bucketRangeLabel(
  bucketStartUtc: string,
  bucketSeconds: number,
  toUtc: string,
  timeZone: string,
): string {
  const r = bucketRange(bucketStartUtc, bucketSeconds, toUtc)
  return `${formatIsoInTimeZone(r.from, timeZone)} ～ ${formatIsoInTimeZone(r.to, timeZone)}`
}
