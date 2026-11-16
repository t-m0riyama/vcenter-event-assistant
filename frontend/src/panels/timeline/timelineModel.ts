import { formatIsoInTimeZone, parseApiUtcInstantMs } from '../../datetime/formatIsoInTimeZone'
import type {
  IncidentTimelineViewRequest,
  TimelineOmittedSource,
  TimelineOverviewBucket,
  TimelineViewItem,
} from '../../api/schemas'
import type { MetricsFocus } from '../../hooks/metricsReplay'
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
    metric_threshold_cpu_pct: conditions.cpuThresholdPct,
    metric_threshold_memory_pct: conditions.memoryThresholdPct,
  }
  if (conditions.anchor) body.anchor = conditions.anchor
  if (conditions.vcenterId) body.vcenter_id = conditions.vcenterId
  if (conditions.entity) body.entity = conditions.entity
  return body
}

/**
 * 行の時刻の前後 5 分と vCenter をイベント・ログのタブへ渡すハッシュ。vCenter が無い行は null。
 * まとめた行は、最初の時刻の 5 分前から最後の時刻（`end_utc`）の 5 分後までを渡す。
 */
export function correlationHashForItem(tab: 'events' | 'logs', item: TimelineViewItem): string | null {
  if (!item.vcenter_id) return null
  const t = parseApiUtcInstantMs(item.timestamp_utc)
  if (!Number.isFinite(t)) return null
  const endRaw = item.end_utc ? parseApiUtcInstantMs(item.end_utc) : t
  const end = Number.isFinite(endRaw) ? Math.max(endRaw, t) : t
  return correlationHash(tab, {
    vcenterId: item.vcenter_id,
    from: iso(t - CORRELATION_HALF_WIDTH_MS),
    to: iso(end + CORRELATION_HALF_WIDTH_MS),
  })
}

/** グラフで開くときに行の時刻の前後に取る幅（ミリ秒）。 */
export const METRICS_FOCUS_HALF_WIDTH_MS = 30 * 60_000

/**
 * 行の時刻の前後 30 分と vCenter、目印（行の最初の時刻）をグラフのタブへ渡す条件。metric のアラートと
 * メトリクスの超過区間は指標、イベントは種別も渡す。超過区間の目印はピークの時刻（無ければ区間の開始）。
 * vCenter が無い行・時刻が読めない行・指標を持たないログの行は null。まとめた行・区間は `end_utc` の 30 分後まで。
 */
export function metricsFocusForItem(item: TimelineViewItem): MetricsFocus | null {
  if (!item.vcenter_id || item.kind === 'log') return null
  const t = parseApiUtcInstantMs(item.timestamp_utc)
  if (!Number.isFinite(t)) return null
  const endRaw = item.end_utc ? parseApiUtcInstantMs(item.end_utc) : t
  const end = Number.isFinite(endRaw) ? Math.max(endRaw, t) : t
  const focus: MetricsFocus = {
    from: iso(t - METRICS_FOCUS_HALF_WIDTH_MS),
    to: iso(end + METRICS_FOCUS_HALF_WIDTH_MS),
    vcenterId: item.vcenter_id,
    markerUtc: iso(t),
  }
  // metric のアラートはその指標を、イベントはその種別の件数の重ね表示を渡す
  if ((item.kind === 'alert' || item.kind === 'metric') && item.ref.metric_key) focus.metricKey = item.ref.metric_key
  if (item.kind === 'metric' && item.ref.peak_at_utc) {
    const peak = parseApiUtcInstantMs(item.ref.peak_at_utc)
    if (Number.isFinite(peak)) focus.markerUtc = iso(peak)
  }
  if (item.kind === 'event' && item.ref.event_type) focus.chartEventType = item.ref.event_type
  return focus
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

/** 継続時間を「10 分」「1 時間 5 分」「1 日 3 時間」のように書く。負の値は 0 秒。 */
export function formatDurationMs(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const days = Math.floor(total / 86_400)
  const hours = Math.floor((total % 86_400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const parts: string[] = []
  if (days > 0) {
    parts.push(`${days} 日`)
    if (hours > 0) parts.push(`${hours} 時間`)
  } else if (hours > 0) {
    parts.push(`${hours} 時間`)
    if (minutes > 0) parts.push(`${minutes} 分`)
  } else if (minutes > 0) {
    parts.push(`${minutes} 分`)
  } else {
    parts.push(`${seconds} 秒`)
  }
  return parts.join(' ')
}

/** メトリクスの超過区間の長さ（ミリ秒）。単発（`end_utc` が無い）は null。 */
export function intervalDurationMs(item: Pick<TimelineViewItem, 'timestamp_utc' | 'end_utc'>): number | null {
  if (!item.end_utc) return null
  const start = parseApiUtcInstantMs(item.timestamp_utc)
  const end = parseApiUtcInstantMs(item.end_utc)
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : null
}

/** メトリクスを省いたか。省いたときの `metric_breach` は当てにならないので、俯瞰に系列を出さない。 */
export function isMetricOmitted(omitted: readonly TimelineOmittedSource[]): boolean {
  return omitted.some((o) => o.source === 'metric')
}

/** 件数が多すぎて一覧から省いた種別の知らせ（1 種別 1 文）。 */
export function omittedSourceMessages(omitted: readonly TimelineOmittedSource[]): string[] {
  return omitted.map((o) => {
    if (o.source === 'log') {
      return 'ログは件数が多すぎるため、一覧から省いています（件数は上のグラフに出ています）。期間を短くするか、対象を絞ってください。'
    }
    if (o.source === 'metric') {
      return 'メトリクスの超過区間は件数が多すぎるため、一覧から省いています（グラフにも出ていません）。しきい値を上げるか、期間を短くするか、対象を絞ってください。'
    }
    return `${o.source} は件数が多すぎるため、一覧から省いています。期間を短くするか、対象を絞ってください。`
  })
}

/** 省いた種別の画面上の名前（状態の欄に使う）。 */
export function omittedKindLabels(omitted: readonly TimelineOmittedSource[]): string[] {
  return omitted.map((o) => (o.source === 'log' ? 'ログ' : o.source === 'metric' ? 'メトリクス' : o.source))
}

/**
 * メトリクスの超過区間の文。`format` は時刻の書き方（設定のタイムゾーン）。
 * 期間の端で続いている超過は、始まり・終わりを言い切らず、継続時間は「N 分以上」にする
 * （`continues_from_before`: 開始は期間の開始前、`continues_after`: 終わりは期間の終わりより後）。
 */
export function metricIntervalText(
  item: Pick<TimelineViewItem, 'timestamp_utc' | 'end_utc' | 'ref'>,
  format: (iso: string) => string,
): string {
  const before = item.ref.continues_from_before === true
  const after = item.ref.continues_after === true
  const duration = intervalDurationMs(item)
  const start = format(item.timestamp_utc)
  const end = item.end_utc && duration !== null ? format(item.end_utc) : null
  const length = duration === null ? '' : formatDurationMs(duration)
  const head = before ? '期間の開始前から' : null
  if (after) {
    const tail = end === null ? '期間の終わりでも継続中' : `期間の終わり（${end}）でも継続中。継続 ${length}以上`
    return `超過区間: ${head ?? `${start} から`}（${tail}）`
  }
  if (end === null) return before ? `超過区間: ${head} ${start} まで（継続）` : `超過区間: ${start}（単発）`
  return `超過区間: ${head ? `${head} ` : `${start} から `}${end} まで（継続 ${length}${before ? '以上' : ''}）`
}
