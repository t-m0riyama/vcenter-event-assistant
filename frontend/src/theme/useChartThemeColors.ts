import { useMemo } from 'react'
import { useTheme } from './useTheme'
import {
  CHART_STROKE_GRID,
  CHART_STROKE_PRIMARY,
  CHART_STROKE_SECONDARY,
} from '../styles/chartStrokes'

export type ChartThemeColors = {
  grid: string
  primary: string
  secondary: string
  axisTick: string
}

/**
 * Reads chart-related colors from CSS variables after `data-theme` updates (Recharts SVG attributes).
 */
export function useChartThemeColors(): ChartThemeColors {
  const { effectiveTheme } = useTheme()
  return useMemo(() => {
    void effectiveTheme
    const root = document.documentElement
    const cs = getComputedStyle(root)
    const grid =
      cs.getPropertyValue('--color-chart-grid').trim() || CHART_STROKE_GRID
    const primary =
      cs.getPropertyValue('--color-chart-primary').trim() || CHART_STROKE_PRIMARY
    const secondary =
      cs.getPropertyValue('--color-chart-secondary').trim() ||
      CHART_STROKE_SECONDARY
    const axisTick =
      cs.getPropertyValue('--color-text-secondary').trim() ||
      CHART_STROKE_GRID
    return { grid, primary, secondary, axisTick }
  }, [effectiveTheme])
}
