import { createContext } from 'react'
import type { ThemePreference } from './themeStorage'

export type ThemeContextValue = {
  /** 一般設定のユーザー選択（ライト / ダーク / システム）。 */
  readonly preference: ThemePreference
  /** ``data-theme`` とチャートに使う解決済み light / dark。 */
  readonly effectiveTheme: 'light' | 'dark'
  readonly setPreference: (preference: ThemePreference) => void
}

/** テーマ Context。 */
export const ThemeContext = createContext<ThemeContextValue | null>(null)
