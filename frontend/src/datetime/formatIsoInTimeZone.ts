/** Format an ISO 8601 instant string for display in the given IANA time zone. */
export function formatIsoInTimeZone(
  isoString: string,
  timeZone: string,
  locale?: string,
): string {
  const d = new Date(isoString)
  if (Number.isNaN(d.getTime())) {
    return '—'
  }
  try {
    return new Intl.DateTimeFormat(locale, {
      dateStyle: 'short',
      timeStyle: 'medium',
      timeZone,
    }).format(d)
  } catch {
    // Invalid timeZone or environment quirks must not crash the UI.
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
  }
}
