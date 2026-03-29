import { utcIsoToZonedLocalDateTimeInput } from './zonedLocalDateTime'

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TIME_RE = /^\d{2}:\d{2}$/

export type ZonedRangeParts = {
  readonly fromDate: string
  readonly fromTime: string
  readonly toDate: string
  readonly toTime: string
}

/** グラフタブの初期表示など「直近 N」相対窓のデフォルト長さ（ミリ秒）。24 時間。 */
export const METRICS_DEFAULT_ROLLING_DURATION_MS = 86400000

/** Initial empty range (no `from` / `to` filter). */
export const EMPTY_ZONED_RANGE_PARTS: ZonedRangeParts = {
  fromDate: '',
  fromTime: '',
  toDate: '',
  toTime: '',
}

/**
 * Combines HTML `date` / `time` values into `YYYY-MM-DDTHH:mm` for {@link zonedLocalDateTimeToUtcIso}.
 * Empty date means that endpoint is unset. If date is set but time is empty, uses 00:00 for start and 23:59 for end.
 */
export function combineDateAndOptionalTime(
  dateStr: string,
  timeStr: string,
  defaultWhenTimeEmpty: 'start' | 'end',
): string {
  const d = dateStr.trim()
  if (!d) return ''
  if (!DATE_RE.test(d)) return ''
  const t = timeStr.trim()
  if (t) {
    if (!TIME_RE.test(t)) return ''
    return `${d}T${t}`
  }
  return defaultWhenTimeEmpty === 'end' ? `${d}T23:59` : `${d}T00:00`
}

/**
 * Builds combined range strings for API resolution from four field values.
 */
export function zonedRangePartsToCombinedInputs(parts: ZonedRangeParts): {
  rangeFromInput: string
  rangeToInput: string
} {
  return {
    rangeFromInput: combineDateAndOptionalTime(
      parts.fromDate,
      parts.fromTime,
      'start',
    ),
    rangeToInput: combineDateAndOptionalTime(parts.toDate, parts.toTime, 'end'),
  }
}

/** Splits `YYYY-MM-DDTHH:mm` into date + time for native inputs. */
export function splitZonedLocalDateTimeInput(combined: string): {
  date: string
  time: string
} {
  const t = combined.trim()
  if (!t.includes('T')) return { date: '', time: '' }
  const [d, tm] = t.split('T', 2)
  if (!DATE_RE.test(d)) return { date: '', time: '' }
  const timeOnly = tm?.slice(0, 5) ?? ''
  if (timeOnly && !TIME_RE.test(timeOnly)) return { date: d, time: '' }
  return { date: d, time: timeOnly }
}

/**
 * Sets range to [now - durationMs, now] expressed as wall time in `timeZone`.
 */
export function presetRelativeRangeWallParts(
  durationMs: number,
  timeZone: string,
): ZonedRangeParts {
  const now = Date.now()
  const fromIso = new Date(now - durationMs).toISOString()
  const toIso = new Date(now).toISOString()
  const fromC = utcIsoToZonedLocalDateTimeInput(fromIso, timeZone)
  const toC = utcIsoToZonedLocalDateTimeInput(toIso, timeZone)
  if (!fromC || !toC) return { ...EMPTY_ZONED_RANGE_PARTS }
  const a = splitZonedLocalDateTimeInput(fromC)
  const b = splitZonedLocalDateTimeInput(toC)
  return {
    fromDate: a.date,
    fromTime: a.time,
    toDate: b.date,
    toTime: b.time,
  }
}

/**
 * {@link presetRelativeRangeWallParts} が空になる場合（無効な IANA など）に UTC で再試行する。
 */
export function presetRelativeRangeWallPartsWithUtcFallback(
  durationMs: number,
  timeZone: string,
): ZonedRangeParts {
  const p = presetRelativeRangeWallParts(durationMs, timeZone)
  if (p.fromDate && p.toDate) return p
  return presetRelativeRangeWallParts(durationMs, 'UTC')
}

/**
 * ローリング窓の長さをグラフ見出し・折りたたみ要約用の短い日本語にする。
 */
export function formatRollingDurationLabel(durationMs: number): string {
  if (durationMs === METRICS_DEFAULT_ROLLING_DURATION_MS) {
    return '直近24時間'
  }
  const days = durationMs / 86400000
  if (Number.isInteger(days) && days >= 1 && days <= 366) {
    return `直近 ${days} 日`
  }
  const hours = Math.round(durationMs / 3600000)
  if (hours >= 1 && hours < 48) {
    return `直近 ${hours} 時間`
  }
  return `直近 ${Math.max(1, Math.round(durationMs / 86400000))} 日`
}
