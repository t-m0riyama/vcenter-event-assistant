import { utcIsoToZonedLocalDateTimeInput } from './zonedLocalDateTime'

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const TIME_RE = /^\d{2}:\d{2}$/

export type ZonedRangeParts = {
  readonly fromDate: string
  readonly fromTime: string
  readonly toDate: string
  readonly toTime: string
}

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
