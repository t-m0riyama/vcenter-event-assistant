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

/**
 * Formats Recharts axis/tooltip values (often `Date` for time scales, or ms number).
 * Avoids `String(date)` which follows the browser locale, not the selected IANA zone.
 */
export function formatChartAxisTick(value: unknown, timeZone: string): string {
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
  return formatIsoInTimeZone(new Date(ms).toISOString(), timeZone, { omitSeconds: true })
}
