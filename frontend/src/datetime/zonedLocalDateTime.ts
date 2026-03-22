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
 * Intl の `formatToParts` から壁時計を取得する（`hour: 24` は正規化しない）。
 */
function getWallClockInZoneRaw(utcMs: number, timeZone: string): ZonedWallParts {
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
 * `hour === 24` が「その暦日の終了（＝翌暦日の 0 時）」か、
 * 「当日 0 時」の別表記かを、1 分前の暦日と比較して判定する。
 */
function isHour24EndOfCalendarDay(
  utcMs: number,
  timeZone: string,
  wall: ZonedWallParts,
): boolean {
  const prev = getWallClockInZoneRaw(utcMs - 60000, timeZone)
  return (
    prev.year === wall.year &&
    prev.month === wall.month &&
    prev.day === wall.day
  )
}

/**
 * Calendar parts for an instant, in the given IANA time zone (wall clock).
 */
export function getWallClockInZone(utcMs: number, timeZone: string): ZonedWallParts {
  const raw = getWallClockInZoneRaw(utcMs, timeZone)
  let { year, month, day, hour, minute } = raw

  /**
   * `hour === 24` は (1) その日の終了＝翌暦日 0:00、(2) 当日 0:00 の別表記 の両方がありうる。
   * (1) のみ暦日を +1 する。(2) は直前の分が前日のため `isHour24EndOfCalendarDay` が false になる。
   */
  if (hour === 24) {
    hour = 0
    if (!isHour24EndOfCalendarDay(utcMs, timeZone, raw)) {
      return { year, month, day, hour, minute }
    }
    const next = new Date(Date.UTC(year, month - 1, day + 1))
    year = next.getUTCFullYear()
    month = next.getUTCMonth() + 1
    day = next.getUTCDate()
  }
  return {
    year,
    month,
    day,
    hour,
    minute,
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
 * 指定した暦日のローカル 00:00 に相当する UTC エポック ms。存在しない日（うるう日など）や DST ギャップでは `null`。
 */
export function zonedCalendarDateMidnightUtcMs(
  year: number,
  month: number,
  day: number,
  timeZone: string,
): number | null {
  const iso = zonedLocalDateTimeToUtcIso(`${year}-${pad2(month)}-${pad2(day)}T00:00`, timeZone)
  if (!iso) return null
  return parseApiUtcInstantMs(iso)
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
