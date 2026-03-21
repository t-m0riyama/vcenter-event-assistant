import { parseApiUtcInstantMs } from './formatIsoInTimeZone'

const DATETIME_LOCAL_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}

export type ZonedWallParts = {
  readonly year: number
  readonly month: number
  readonly day: number
  readonly hour: number
  readonly minute: number
}

/**
 * Parses `YYYY-MM-DDTHH:mm` (no offset). Does not use `Date` parsing (which is local/UTC ambiguous).
 */
export function parseZonedLocalDateTimeInput(s: string): {
  year: number
  month: number
  day: number
  hour: number
  minute: number
} | null {
  const t = s.trim()
  if (!DATETIME_LOCAL_RE.test(t)) return null
  const [datePart, timePart] = t.split('T')
  const [ys, ms, ds] = datePart.split('-')
  const [hs, mins] = timePart.split(':')
  const year = Number(ys)
  const month = Number(ms)
  const day = Number(ds)
  const hour = Number(hs)
  const minute = Number(mins)
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    !Number.isInteger(hour) ||
    !Number.isInteger(minute)
  ) {
    return null
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  if (hour > 23 || minute > 59) return null
  return { year, month, day, hour, minute }
}

/**
 * Calendar parts for an instant, in the given IANA time zone (wall clock).
 */
export function getWallClockInZone(utcMs: number, timeZone: string): ZonedWallParts {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  const parts = fmt.formatToParts(new Date(utcMs))
  const map: Record<string, string> = {}
  for (const p of parts) {
    if (p.type !== 'literal') map[p.type] = p.value
  }
  return {
    year: Number(map.year),
    month: Number(map.month),
    day: Number(map.day),
    hour: Number(map.hour),
    minute: Number(map.minute),
  }
}

/**
 * Interprets `YYYY-MM-DDTHH:mm` as wall time in `timeZone` and returns a UTC ISO string (`Z`),
 * or `null` if the zone is invalid or the local time does not exist (e.g. DST gap).
 */
export function zonedLocalDateTimeToUtcIso(dateTimeLocal: string, timeZone: string): string | null {
  const parsed = parseZonedLocalDateTimeInput(dateTimeLocal)
  if (!parsed) return null
  const { year, month, day, hour, minute } = parsed
  try {
    new Intl.DateTimeFormat('en-US', { timeZone }).format(0)
  } catch {
    return null
  }

  const anchor = Date.UTC(year, month - 1, day, hour, minute)
  const lo = anchor - 3 * 86400000
  const hi = anchor + 3 * 86400000

  for (let utcMs = lo; utcMs <= hi; utcMs += 60000) {
    const w = getWallClockInZone(utcMs, timeZone)
    if (
      w.year === year &&
      w.month === month &&
      w.day === day &&
      w.hour === hour &&
      w.minute === minute
    ) {
      return new Date(utcMs).toISOString()
    }
  }
  return null
}

/**
 * Formats a UTC ISO instant as `YYYY-MM-DDTHH:mm` in the given IANA zone (for inputs).
 */
export function utcIsoToZonedLocalDateTimeInput(iso: string, timeZone: string): string {
  const ms = parseApiUtcInstantMs(iso)
  if (!Number.isFinite(ms)) return ''
  try {
    const w = getWallClockInZone(ms, timeZone)
    return `${w.year}-${pad2(w.month)}-${pad2(w.day)}T${pad2(w.hour)}:${pad2(w.minute)}`
  } catch {
    return ''
  }
}

/** `fromUtcIso` &lt; `toUtcIso` (strict). */
export function isValidUtcRangeOrder(fromUtcIso: string, toUtcIso: string): boolean {
  const a = parseApiUtcInstantMs(fromUtcIso)
  const b = parseApiUtcInstantMs(toUtcIso)
  return Number.isFinite(a) && Number.isFinite(b) && a < b
}
