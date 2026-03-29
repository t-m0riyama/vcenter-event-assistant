import {
  getWallClockInZone,
  zonedCalendarDateMidnightUtcMs,
} from './zonedLocalDateTime'

export type FormatIsoInTimeZoneOptions = {
  locale?: string
  /** When true, omit seconds (e.g. chart time axis). Uses `timeStyle: 'short'`. */
  omitSeconds?: boolean
}

/**
 * Parse API datetime strings as UTC when the server omits `Z` (naive ISO).
 * ECMAScript treats `YYYY-MM-DDTHH:mm:ss` without offset as *local* time, which
 * shifts instants relative to UTC storage (e.g. 9h in JST vs UTC).
 */
export function parseApiUtcInstantMs(isoString: string): number {
  const s = isoString.trim()
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)) {
    return new Date(`${s}Z`).getTime()
  }
  return new Date(s).getTime()
}

/** Format an ISO 8601 instant string for display in the given IANA time zone. */
export function formatIsoInTimeZone(
  isoString: string,
  timeZone: string,
  localeOrOptions?: string | FormatIsoInTimeZoneOptions,
): string {
  const d = new Date(parseApiUtcInstantMs(isoString))
  if (Number.isNaN(d.getTime())) {
    return '—'
  }
  const locale = typeof localeOrOptions === 'string' ? localeOrOptions : localeOrOptions?.locale
  const omitSeconds =
    typeof localeOrOptions === 'object' && localeOrOptions !== null && localeOrOptions.omitSeconds === true
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'short',
      timeStyle: omitSeconds ? 'short' : 'medium',
      timeZone,
    }).format(d)
  } catch {
    // Invalid timeZone or environment quirks must not crash the UI.
    const sliceEnd = omitSeconds ? 16 : 19
    return d.toISOString().replace('T', ' ').slice(0, sliceEnd) + ' UTC'
  }
}

/** Recharts passes either `{ value, coordinate, ... }` or the raw tick value depending on version/path. */
export function extractTickAxisValue(payload: unknown): unknown {
  if (payload != null && typeof payload === 'object' && 'value' in payload) {
    return (payload as { value: unknown }).value
  }
  return payload
}

/** `formatChartAxisTick` のオプション */
export type FormatChartAxisTickOptions = {
  /** 比較用の「今」。省略時は `Date.now()`（テスト用に固定可） */
  readonly nowMs?: number
  /**
   * 表示期間が短いとき true。月日を出さず時刻（時分）のみにする。
   * 既存の年省略ロジックより優先される。
   */
  readonly omitMonthDay?: boolean
}

/**
 * `Intl.DateTimeFormat` が失敗したとき、`omitMonthDay` 用に UTC の時分のみを返す（日付・年は含めない）。
 */
function formatUtcHourMinuteForChartTick(ms: number): string {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return '—'
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${hh}:${mm} UTC`
}

/**
 * `Intl` 失敗時の「年なし」相当（月日＋時分、UTC）。4 桁の暦年は含めない。
 */
function formatUtcMonthDayHourMinuteForChartTick(ms: number): string {
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return '—'
  const month = d.getUTCMonth() + 1
  const day = d.getUTCDate()
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${month}/${day} ${hh}:${mm} UTC`
}

/**
 * 月日なし（時分のみ）。短いレンジの X 軸用。
 */
function formatChartAxisTickTimeOnly(ms: number, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      hourCycle: 'h23',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(ms))
  } catch {
    return formatUtcHourMinuteForChartTick(ms)
  }
}

/**
 * 年なし（月日＋時分）。`formatIsoInTimeZone` の omitSeconds と同様に秒は出さない。
 */
function formatChartAxisTickWithoutYear(ms: number, timeZone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone,
      hourCycle: 'h23',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(ms))
  } catch {
    return formatUtcMonthDayHourMinuteForChartTick(ms)
  }
}

/**
 * 同年、または昨年で「今年の同じ月日」がまだ来ていない場合は年を省略する。
 */
function shouldOmitYearInChartAxis(
  tickMs: number,
  timeZone: string,
  nowMs: number,
): boolean {
  let wallTick: ReturnType<typeof getWallClockInZone>
  let wallNow: ReturnType<typeof getWallClockInZone>
  try {
    wallTick = getWallClockInZone(tickMs, timeZone)
    wallNow = getWallClockInZone(nowMs, timeZone)
  } catch {
    return false
  }

  const yTick = wallTick.year
  const yNow = wallNow.year

  if (yTick === yNow) return true

  if (yTick === yNow - 1) {
    const sameMdThisYear = zonedCalendarDateMidnightUtcMs(
      yNow,
      wallTick.month,
      wallTick.day,
      timeZone,
    )
    if (sameMdThisYear === null) return false
    return sameMdThisYear > nowMs
  }

  return false
}

/**
 * Formats Recharts axis/tooltip values (often `Date` for time scales, or ms number).
 * Avoids `String(date)` which follows the browser locale, not the selected IANA zone.
 *
 * 同年は `YYYY/` を省略し、昨年で「今年の同じ月日」がまだ未来なら省略（曖昧な場合は年付き）。
 */
export function formatChartAxisTick(
  value: unknown,
  timeZone: string,
  options?: FormatChartAxisTickOptions,
): string {
  if (value == null) return ''
  let ms: number
  if (value instanceof Date) {
    ms = value.getTime()
  } else if (typeof value === 'number' && Number.isFinite(value)) {
    ms = value
  } else if (typeof value === 'string') {
    const parsed = parseApiUtcInstantMs(value)
    if (!Number.isFinite(parsed)) return value
    ms = parsed
  } else {
    return String(value)
  }
  if (!Number.isFinite(ms)) return String(value)

  if (options?.omitMonthDay === true) {
    return formatChartAxisTickTimeOnly(ms, timeZone)
  }

  const nowMs = options?.nowMs ?? Date.now()
  if (shouldOmitYearInChartAxis(ms, timeZone, nowMs)) {
    return formatChartAxisTickWithoutYear(ms, timeZone)
  }
  return formatIsoInTimeZone(new Date(ms).toISOString(), timeZone, { omitSeconds: true })
}

/** ツールチップ用の `formatChartAxisTick` オプション（日付省略のみ常にオフ）。 */
export type FormatChartTooltipLabelOptions = Pick<FormatChartAxisTickOptions, 'nowMs'>

/**
 * メトリクスグラフの Recharts Tooltip 用ラベル。
 * X 軸が短いレンジで `omitMonthDay` により時刻のみでも、ツールチップでは常に月日を含める。
 */
export function formatChartTooltipLabel(
  value: unknown,
  timeZone: string,
  options?: FormatChartTooltipLabelOptions,
): string {
  return formatChartAxisTick(value, timeZone, { ...(options ?? {}), omitMonthDay: false })
}
