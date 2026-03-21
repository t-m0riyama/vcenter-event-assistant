import { createContext } from 'react'
import type { ThemePreference } from './themeStorage'

export type ThemeContextValue = {
  /** User choice in 一般 settings (ライト / ダーク / システム). */
  readonly preference: ThemePreference
  /** Resolved light or dark for `data-theme` and charts. */
  readonly effectiveTheme: 'light' | 'dark'
  readonly setPreference: (preference: ThemePreference) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)
