export const DISPLAY_TIME_ZONE_STORAGE_KEY = 'vea.displayTimeZone'

export function getDefaultBrowserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function readStoredTimeZone(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)
}

export function writeStoredTimeZone(tz: string): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, tz)
}

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
