/** タイムラインのアラート Top N 表示件数の既定値。 */
export const DEFAULT_ALERT_TOP_N = 7
/** localStorage キー（アラート Top N）。 */
export const ALERT_TOP_N_STORAGE_KEY = 'vea.timeline.alert_top_n'

/** 保存値を 1..20 の整数にパースする。無効時は null。 */
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

/** 初回表示用のアラート Top N（localStorage または既定 7）。 */
export function getInitialAlertTopN(): number {
  if (typeof localStorage === 'undefined') {
    return DEFAULT_ALERT_TOP_N
  }
  const parsed = parseAlertTopN(localStorage.getItem(ALERT_TOP_N_STORAGE_KEY))
  return parsed ?? DEFAULT_ALERT_TOP_N
}
