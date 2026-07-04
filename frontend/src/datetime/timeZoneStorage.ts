/** localStorage に保存する表示 TZ のキー。 */
export const DISPLAY_TIME_ZONE_STORAGE_KEY = 'vea.displayTimeZone'

/** ブラウザの既定 IANA タイムゾーンを返す。 */
export function getDefaultBrowserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** localStorage から保存済み表示 TZ を読む。未設定時は null。 */
export function readStoredTimeZone(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
}

/** 表示 TZ を localStorage に保存する。 */
export function writeStoredTimeZone(tz: string): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, tz)
}

/** 文字列が有効な IANA タイムゾーン名か判定する。 */
export function isValidIanaTimeZone(tz: string): boolean {
  if (!tz.trim()) {
    return false
  }
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz })
    return true
  } catch {
    return false
  }
}
