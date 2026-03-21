export const THEME_STORAGE_KEY = 'vea.theme'

export type ThemePreference = 'light' | 'dark' | 'system'

const PREFERENCES: readonly ThemePreference[] = ['light', 'dark', 'system']

/**
 * Returns true when `value` is a valid persisted theme preference.
 */
export function isValidThemePreference(value: string): value is ThemePreference {
  return (PREFERENCES as readonly string[]).includes(value)
}

/**
 * Reads the stored theme preference, or null when unset / unavailable.
 */
export function readStoredThemePreference(): string | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage.getItem(THEME_STORAGE_KEY)
}

/**
 * Persists the theme preference to localStorage.
 */
export function writeStoredThemePreference(preference: ThemePreference): void {
  if (typeof localStorage === 'undefined') {
    return
  }
  localStorage.setItem(THEME_STORAGE_KEY, preference)
}

/**
 * Resolves the initial preference: stored value when valid, otherwise `system`.
 */
export function resolveInitialThemePreference(): ThemePreference {
  const raw = readStoredThemePreference()
  if (raw && isValidThemePreference(raw)) {
    return raw
  }
  return 'system'
}
