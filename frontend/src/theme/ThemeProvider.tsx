import {
  useCallback,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { ThemeContext, type ThemeContextValue } from './themeContext'
import {
  resolveInitialThemePreference,
  writeStoredThemePreference,
  type ThemePreference,
} from './themeStorage'

function resolveEffectiveTheme(
  preference: ThemePreference,
  systemIsDark: boolean,
): 'light' | 'dark' {
  if (preference === 'light') return 'light'
  if (preference === 'dark') return 'dark'
  return systemIsDark ? 'dark' : 'light'
}

function subscribePrefersDark(onStoreChange: () => void): () => void {
  if (typeof window === 'undefined') {
    return () => {}
  }
  const mq = window.matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', onStoreChange)
  return () => mq.removeEventListener('change', onStoreChange)
}

function getPrefersDarkSnapshot(): boolean {
  if (typeof window === 'undefined') {
    return false
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function getPrefersDarkServerSnapshot(): boolean {
  return false
}

/**
 * Provides theme preference (persisted) and applies `data-theme` on `document.documentElement`.
 */
export function ThemeProvider({ children }: { readonly children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(
    resolveInitialThemePreference,
  )

  const prefersDark = useSyncExternalStore(
    subscribePrefersDark,
    getPrefersDarkSnapshot,
    getPrefersDarkServerSnapshot,
  )

  const effectiveTheme = useMemo(
    () => resolveEffectiveTheme(preference, prefersDark),
    [preference, prefersDark],
  )

  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', effectiveTheme)
  }

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    writeStoredThemePreference(next)
  }, [])

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, effectiveTheme, setPreference }),
    [preference, effectiveTheme, setPreference],
  )

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  )
}
