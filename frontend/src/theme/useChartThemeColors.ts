import { useMemo } from 'react'
import { useTheme } from './useTheme'
import {
  CHART_STROKE_GRID,
  CHART_STROKE_PRIMARY,
  CHART_STROKE_SECONDARY,
} from '../styles/chartStrokes'

const CHART_SERIES_FALLBACK = [
  CHART_STROKE_PRIMARY,
  CHART_STROKE_SECONDARY,
  '#ff9500',
  '#ff3b30',
  '#af52de',
  '#5ac8fa',
  '#ff375f',
  '#6e7785',
] as const

export type ChartThemeColors = {
  grid: string
  primary: string
  secondary: string
  axisTick: string
  /** 多系列（例: `host.*` のホスト別）のストローク。最大 8 色を巡回。 */
  series: readonly string[]
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
    const series: string[] = []
    for (let i = 1; i <= 8; i++) {
      const v = cs.getPropertyValue(`--color-chart-series-${i}`).trim()
      series.push(v || CHART_SERIES_FALLBACK[i - 1])
    }
    return { grid, primary, secondary, axisTick, series }
  }, [effectiveTheme])
}
