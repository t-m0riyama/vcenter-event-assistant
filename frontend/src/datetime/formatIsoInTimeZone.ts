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
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'short',
    timeStyle: 'medium',
    timeZone,
  }).format(d)
}
