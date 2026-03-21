export type FormatIsoInTimeZoneOptions = {
  locale?: string
  /** When true, omit seconds (e.g. chart time axis). Uses `timeStyle: 'short'`. */
  omitSeconds?: boolean
}

/** Format an ISO 8601 instant string for display in the given IANA time zone. */
export function formatIsoInTimeZone(
  isoString: string,
  timeZone: string,
  localeOrOptions?: string | FormatIsoInTimeZoneOptions,
): string {
  const d = new Date(isoString)
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
