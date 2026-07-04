export const DEFAULT_ALERT_TOP_N = 7
export const ALERT_TOP_N_STORAGE_KEY = 'vea.timeline.alert_top_n'

export function parseAlertTopN(rawValue: string | null): number | null {
  if (rawValue == null || rawValue.trim() === '') {
    return null
  }
  const parsed = Number(rawValue)
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) {
    return null
  }
  return parsed
}

export function getInitialAlertTopN(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_ALERT_TOP_N
  }
  const parsed = parseAlertTopN(localStorage.getItem(ALERT_TOP_N_STORAGE_KEY))
  return parsed ?? DEFAULT_ALERT_TOP_N
}
