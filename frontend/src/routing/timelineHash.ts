import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import {
  DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
  isValidMetricThresholdPercent,
} from '../hooks/periodMetricThresholdDefaults'
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

/** 画面から選べる出来事の種別。 */
export type TimelineSourceKind = 'event' | 'alert' | 'metric' | 'log'
export const TIMELINE_SOURCE_KINDS: readonly TimelineSourceKind[] = ['event', 'alert', 'metric', 'log']

/** タイムラインの条件。URL のハッシュと 1 対 1 に対応する。 */
export type TimelineConditions = {
  readonly range: TimelineRange
  /** 起点の時刻（UTC の ISO 8601）。 */
  readonly anchor: string | null
  readonly vcenterId: string
  readonly entity: string
  readonly entityMoid: string | null
  readonly minScore: number
  readonly sources: readonly TimelineSourceKind[]
  /** CPU 使用率の超過区間のしきい値（%）。ディスクとネットワークは対象外（値が KB/s のため）。 */
  readonly cpuThresholdPct: number
  /** メモリ使用率の超過区間のしきい値（%）。 */
  readonly memoryThresholdPct: number
}

export const DEFAULT_TIMELINE_MIN_SCORE = 1

export const DEFAULT_TIMELINE_CONDITIONS: TimelineConditions = {
  range: { mode: 'rolling', durationMs: HOUR_MS },
  anchor: null,
  vcenterId: '',
  entity: '',
  entityMoid: null,
  minScore: DEFAULT_TIMELINE_MIN_SCORE,
  sources: TIMELINE_SOURCE_KINDS,
  cpuThresholdPct: DEFAULT_METRIC_THRESHOLD_CPU_PCT,
  memoryThresholdPct: DEFAULT_METRIC_THRESHOLD_MEMORY_PCT,
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** `Z` の無い時刻もブラウザのローカル時刻ではなく UTC として読む。読めなければ null。 */
function validIso(value: string): string | null {
  const v = value.trim()
  const ms = parseApiUtcInstantMs(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v) ? `${v}:00` : v)
  return Number.isFinite(ms) ? new Date(ms).toISOString() : null
}

/** URL を読んだ結果。`issue` があるときは、条件のうち読めなかった部分を既定にしてある。 */
export type ParsedTimelineHash = { readonly conditions: TimelineConditions; readonly issue: string | null }

function readRange(params: URLSearchParams, issues: string[]): TimelineRange {
  const rangeKey = params.get('range')
  if (rangeKey !== null) {
    const preset = TIMELINE_ROLLING_PRESETS.find((p) => p.key === rangeKey)
    if (preset) return { mode: 'rolling', durationMs: preset.durationMs }
    issues.push(`URL の range「${rangeKey}」は使えません（1h / 6h / 24h のいずれかです）。`)
    return DEFAULT_TIMELINE_CONDITIONS.range
  }
  const rawFrom = params.get('from')
  const rawTo = params.get('to')
  if (rawFrom === null && rawTo === null) return DEFAULT_TIMELINE_CONDITIONS.range
  if (rawFrom === null || rawTo === null) {
    issues.push('URL の期間は from と to の両方が必要です。')
    return DEFAULT_TIMELINE_CONDITIONS.range
  }
  const from = validIso(rawFrom)
  const to = validIso(rawTo)
  if (!from || !to) {
    issues.push('URL の from / to の日時を解釈できません。')
    return DEFAULT_TIMELINE_CONDITIONS.range
  }
  if (Date.parse(from) >= Date.parse(to)) {
    issues.push('URL の期間が不正です。開始（from）は終了（to）より前の時刻にしてください。')
    return DEFAULT_TIMELINE_CONDITIONS.range
  }
  return { mode: 'fixed', from, to }
}

/** URL の閾値（0〜100 の有限な数）。無ければ既定。読めない値は既定にして理由を積む。 */
function readThreshold(params: URLSearchParams, name: string, fallback: number, issues: string[]): number {
  const raw = params.get(name)
  if (raw === null) return fallback
  const n = raw.trim() === '' ? NaN : Number(raw)
  if (isValidMetricThresholdPercent(n)) return n
  issues.push(`URL の ${name} は 0〜100 の数値にしてください。`)
  return fallback
}

/**
 * `#/timeline?...` を条件に戻す。タイムラインのハッシュでない・クエリが無いときは null。
 * 読めない値は黙って既定に置き換えず、`issue` で理由を返す（呼び出し側は読み込まず、URL も書き換えない）。
 */
export function parseTimelineHash(hash: string): ParsedTimelineHash | null {
  const [, query] = hash.split('?', 2)
  if (parseAppHash(hash).tab !== 'timeline' || !query) return null
  const params = new URLSearchParams(query)
  const issues: string[] = []
  const range = readRange(params, issues)

  const rawAnchor = params.get('anchor')
  let anchor: string | null = null
  if (rawAnchor) {
    anchor = validIso(rawAnchor)
    if (!anchor) issues.push('URL の anchor の日時を解釈できません。')
  }

  const vcenterId = params.get('vcenter_id') ?? ''
  let safeVcenterId = vcenterId
  if (vcenterId && !UUID_RE.test(vcenterId)) {
    issues.push('URL の vcenter_id が UUID の形ではありません。')
    safeVcenterId = ''
  }

  const entityMoid = params.get('entity_moid')?.trim() || null
  if (entityMoid && !safeVcenterId) {
    issues.push('URL の entity_moid を使うには有効な vcenter_id が必要です。')
  }

  const cpuThresholdPct = readThreshold(params, 'cpu_threshold', DEFAULT_METRIC_THRESHOLD_CPU_PCT, issues)
  const memoryThresholdPct = readThreshold(params, 'memory_threshold', DEFAULT_METRIC_THRESHOLD_MEMORY_PCT, issues)

  const minScoreRaw = Number(params.get('min_score'))
  const sources = (params.get('sources') ?? '')
    .split(',')
    .filter((s): s is TimelineSourceKind => (TIMELINE_SOURCE_KINDS as readonly string[]).includes(s))
  return {
    conditions: {
      range,
      anchor,
      vcenterId: safeVcenterId,
      entity: (params.get('entity') ?? '').trim(),
      entityMoid: safeVcenterId ? entityMoid : null,
      minScore:
        params.get('min_score') !== null && Number.isInteger(minScoreRaw) && minScoreRaw >= 0 && minScoreRaw <= 100
          ? minScoreRaw
          : DEFAULT_TIMELINE_MIN_SCORE,
      sources: sources.length > 0 ? TIMELINE_SOURCE_KINDS.filter((k) => sources.includes(k)) : TIMELINE_SOURCE_KINDS,
      cpuThresholdPct,
      memoryThresholdPct,
    },
    issue: issues.length > 0 ? issues.join(' ') : null,
  }
}

/** いまのブラウザ URL のハッシュを条件として読む（`parseTimelineHash(window.location.hash)`）。 */
export function readTimelineHash(): ParsedTimelineHash | null {
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
  if (conditions.vcenterId && conditions.entityMoid) params.set('entity_moid', conditions.entityMoid)
  if (conditions.minScore !== DEFAULT_TIMELINE_MIN_SCORE) params.set('min_score', String(conditions.minScore))
  if (conditions.sources.length !== TIMELINE_SOURCE_KINDS.length) params.set('sources', conditions.sources.join(','))
  if (conditions.cpuThresholdPct !== DEFAULT_METRIC_THRESHOLD_CPU_PCT) {
    params.set('cpu_threshold', String(conditions.cpuThresholdPct))
  }
  if (conditions.memoryThresholdPct !== DEFAULT_METRIC_THRESHOLD_MEMORY_PCT) {
    params.set('memory_threshold', String(conditions.memoryThresholdPct))
  }
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

/** 他のタブから開くときの、起点の前後の既定の幅（ミリ秒）。 */
export const TIMELINE_ENTRY_HALF_WIDTH_MS = 30 * 60_000

export type TimelineEntryInput = {
  /** 起点の時刻（ISO 文字列。`Z` が無ければ UTC として読む）。 */
  readonly at: string | null | undefined
  readonly vcenterId?: string | null
  /** 対象名（moid が無ければ部分一致で絞る）。 */
  readonly entity?: string | null
  readonly entityMoid?: string | null
  readonly halfWidthMs?: number
}

/**
 * 他のタブからタイムラインを開くハッシュ。起点の前後（既定 30 分）を期間にし、起点・vCenter・対象を渡す。
 * 時刻が読めないときは null（呼び出し側はリンクを出さない）。`to` が未来でも構わない。
 */
export function timelineEntryHash(input: TimelineEntryInput): string | null {
  const raw = input.at?.trim()
  if (!raw) return null
  const anchorMs = parseApiUtcInstantMs(raw)
  if (!Number.isFinite(anchorMs)) return null
  const half = input.halfWidthMs ?? TIMELINE_ENTRY_HALF_WIDTH_MS
  return buildTimelineHash({
    ...DEFAULT_TIMELINE_CONDITIONS,
    range: { mode: 'fixed', from: new Date(anchorMs - half).toISOString(), to: new Date(anchorMs + half).toISOString() },
    anchor: new Date(anchorMs).toISOString(),
    vcenterId: input.vcenterId ?? '',
    entity: input.entity?.trim() ?? '',
    entityMoid: input.entityMoid?.trim() || null,
  })
}
