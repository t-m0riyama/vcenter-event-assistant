import { useContext } from 'react'
import { ThemeContext } from './themeContext'

/**
 * Returns the current theme preference and the resolved light/dark appearance.
 */
export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return ctx
}
