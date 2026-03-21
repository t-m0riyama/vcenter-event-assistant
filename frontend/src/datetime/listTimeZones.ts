/** Subset when `Intl.supportedValuesOf('timeZone')` is unavailable (older browsers). */
const FALLBACK_TIME_ZONES: readonly string[] = [
  'UTC',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Asia/Shanghai',
  'Asia/Singapore',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Australia/Sydney',
  'Pacific/Auckland',
]

/** Sorted IANA time zone identifiers for select options. */
export function getSortedTimeZoneOptions(): string[] {
  const set = new Set<string>()
  if (typeof Intl !== 'undefined' && 'supportedValuesOf' in Intl) {
    try {
      for (const z of Intl.supportedValuesOf('timeZone')) {
        set.add(z)
      }
    } catch {
      // use fallback only
    }
  }
  for (const z of FALLBACK_TIME_ZONES) {
    set.add(z)
  }
  if (set.size === 0) {
    for (const z of FALLBACK_TIME_ZONES) {
      set.add(z)
    }
  }
  return [...set].sort((a, b) => a.localeCompare(b))
}
