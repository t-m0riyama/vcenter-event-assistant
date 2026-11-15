import { parseAppHash } from './appHashRouting'

const HOUR_MS = 3_600_000

/** 「直近 N 時間」のプリセット。URL では `range=<key>` で表す。 */
export const TIMELINE_ROLLING_PRESETS = [
  { key: '1h', durationMs: HOUR_MS, label: '直近 1 時間' },
  { key: '6h', durationMs: 6 * HOUR_MS, label: '直近 6 時間' },
  { key: '24h', durationMs: 24 * HOUR_MS, label: '直近 24 時間' },
] as const

/** 期間。`rolling` は開くたびに「今から直近 N」になり、`fixed` は UTC の ISO 8601 で固定する。 */
export type TimelineRange =
  | { readonly mode: 'rolling'; readonly durationMs: number }
  | { readonly mode: 'fixed'; readonly from: string; readonly to: string }

/** 画面から選べる出来事の種別（メトリクスとログは API が返すようになったら足す）。 */
export type TimelineSourceKind = 'event' | 'alert'
export const TIMELINE_SOURCE_KINDS: readonly TimelineSourceKind[] = ['event', 'alert']

/** タイムラインの条件。URL のハッシュと 1 対 1 に対応する。 */
export type TimelineConditions = {
  readonly range: TimelineRange
  /** 起点の時刻（UTC の ISO 8601）。 */
  readonly anchor: string | null
  readonly vcenterId: string
  readonly entity: string
  readonly minScore: number
  readonly sources: readonly TimelineSourceKind[]
}

export const DEFAULT_TIMELINE_MIN_SCORE = 1

export const DEFAULT_TIMELINE_CONDITIONS: TimelineConditions = {
  range: { mode: 'rolling', durationMs: HOUR_MS },
  anchor: null,
  vcenterId: '',
  entity: '',
  minScore: DEFAULT_TIMELINE_MIN_SCORE,
  sources: TIMELINE_SOURCE_KINDS,
}

function validIso(value: string | null): string | null {
  if (!value) return null
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null
}

function readRange(params: URLSearchParams): TimelineRange {
  const preset = TIMELINE_ROLLING_PRESETS.find((p) => p.key === params.get('range'))
  if (preset) return { mode: 'rolling', durationMs: preset.durationMs }
  const from = validIso(params.get('from'))
  const to = validIso(params.get('to'))
  if (from && to && Date.parse(from) < Date.parse(to)) return { mode: 'fixed', from, to }
  return DEFAULT_TIMELINE_CONDITIONS.range
}

/** `#/timeline?...` を条件に戻す。タイムラインのハッシュでない・クエリが無いときは null。 */
export function parseTimelineHash(hash: string): TimelineConditions | null {
  const [, query] = hash.split('?', 2)
  if (parseAppHash(hash).tab !== 'timeline' || !query) return null
  const params = new URLSearchParams(query)
  const minScoreRaw = Number(params.get('min_score'))
  const sources = (params.get('sources') ?? '')
    .split(',')
    .filter((s): s is TimelineSourceKind => (TIMELINE_SOURCE_KINDS as readonly string[]).includes(s))
  return {
    range: readRange(params),
    anchor: validIso(params.get('anchor')),
    vcenterId: params.get('vcenter_id') ?? '',
    entity: (params.get('entity') ?? '').trim(),
    minScore:
      params.get('min_score') !== null && Number.isInteger(minScoreRaw) && minScoreRaw >= 0 && minScoreRaw <= 100
        ? minScoreRaw
        : DEFAULT_TIMELINE_MIN_SCORE,
    sources: sources.length > 0 ? TIMELINE_SOURCE_KINDS.filter((k) => sources.includes(k)) : TIMELINE_SOURCE_KINDS,
  }
}

/** いまのブラウザ URL のハッシュを条件として読む（`parseTimelineHash(window.location.hash)`）。 */
export function readTimelineHash(): TimelineConditions | null {
  return parseTimelineHash(window.location.hash)
}

/**
 * 条件を共有できるハッシュにする。既定値の項目は省略する。
 * 「直近 N 時間」は `range=1h` のように書き、`from` / `to` を固定しない。
 */
export function buildTimelineHash(conditions: TimelineConditions): string {
  const params = new URLSearchParams()
  const { range } = conditions
  if (range.mode === 'rolling') {
    const preset = TIMELINE_ROLLING_PRESETS.find((p) => p.durationMs === range.durationMs)
    params.set('range', preset?.key ?? DEFAULT_PRESET_KEY)
  } else {
    params.set('from', range.from)
    params.set('to', range.to)
  }
  if (conditions.anchor) params.set('anchor', conditions.anchor)
  if (conditions.vcenterId) params.set('vcenter_id', conditions.vcenterId)
  if (conditions.entity) params.set('entity', conditions.entity)
  if (conditions.minScore !== DEFAULT_TIMELINE_MIN_SCORE) params.set('min_score', String(conditions.minScore))
  if (conditions.sources.length !== TIMELINE_SOURCE_KINDS.length) params.set('sources', conditions.sources.join(','))
  return `#/timeline?${params}`
}

const DEFAULT_PRESET_KEY = TIMELINE_ROLLING_PRESETS[0].key

/** URL のハッシュを条件に合わせて書き換える（履歴は replace）。同じ値なら何もしない。 */
export function replaceTimelineHash(conditions: TimelineConditions): void {
  const next = buildTimelineHash(conditions)
  if (window.location.hash === next) return
  const { pathname, search } = window.location
  window.history.replaceState(null, '', `${pathname}${search}${next}`)
}
