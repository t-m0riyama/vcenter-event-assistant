import { useCallback, useLayoutEffect, useMemo, useState, type ReactNode, type RefObject } from 'react'
import type { LegendPayload, TooltipProps } from 'recharts'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { FormatChartAxisTickOptions } from '../../datetime/formatIsoInTimeZone'
import {
  formatMetricChartSeriesLegendName,
  type BuildMetricsChartModelResult,
  type MetricChartRowHost,
  type MetricChartRowSingle,
} from '../../metrics/buildMetricsChartModel'
import { formatChartTooltipNumber } from '../../metrics/export/chartYAxisFormat'
import { MetricsChartErrorBoundary } from '../../metrics/MetricsChartErrorBoundary'
import type { useChartThemeColors } from '../../theme/useChartThemeColors'
import {
  xAxisBottomMarginForWidth,
  xAxisMinTickGapForWidth,
  xAxisTickCountForWidth,
} from './chartXAxisLayout'
import { MetricsXAxisTick } from './MetricsXAxisTick'

/** データ点はホバー時のみ表示して線を主役にする */
const LINE_CHART_ACTIVE_DOT = { r: 4, strokeWidth: 0 } as const

type ChartColors = ReturnType<typeof useChartThemeColors>

type MetricsChartProps = {
  chartResetKey: string
  timeZone: string
  metricKey: string
  chartWrapRef: RefObject<HTMLDivElement | null>
  chartColors: ChartColors
  metricsChartMargin: { top: number; right: number; left: number }
  chartModel: BuildMetricsChartModelResult
  chartData: MetricChartRowSingle[] | MetricChartRowHost[]
  hiddenSeriesDataKeys: Set<string>
  onMetricsLegendClick: (data: LegendPayload) => void
  vcenterLabelForChart: string
  metricsChartTitleLines: { line1: string; line2: string }
  metricsChartLegendName: string
  eventSeriesLegendName: string
  chartAxisTickFormatOptions: FormatChartAxisTickOptions
  formatAxisTimeLabel: (value: unknown) => string
  formatTooltipLabel: (value: unknown) => string
  formatYAxisTickMetric: (value: number) => string
  formatYAxisTickCount: (value: number) => string
  showEventLine: boolean
  leftYAxisLabel: string | undefined
  snapshotChartGuidelineMs: number | null
}

/** メトリクス Recharts グラフ本体。 */
export function MetricsChart({
  chartResetKey,
  timeZone,
  metricKey,
  chartWrapRef,
  chartColors,
  metricsChartMargin,
  chartModel,
  chartData,
  hiddenSeriesDataKeys,
  onMetricsLegendClick,
  vcenterLabelForChart,
  metricsChartTitleLines,
  metricsChartLegendName,
  eventSeriesLegendName,
  chartAxisTickFormatOptions,
  formatAxisTimeLabel,
  formatTooltipLabel,
  formatYAxisTickMetric,
  formatYAxisTickCount,
  showEventLine,
  leftYAxisLabel,
  snapshotChartGuidelineMs,
}: MetricsChartProps) {
  const [chartWrapWidthPx, setChartWrapWidthPx] = useState(0)
  useLayoutEffect(() => {
    const el = chartWrapRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w != null && Number.isFinite(w)) setChartWrapWidthPx(w)
    })
    ro.observe(el)
    setChartWrapWidthPx(el.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [chartWrapRef])

  const xAxisMinTickGap = xAxisMinTickGapForWidth(chartWrapWidthPx)
  const xAxisTickCount = xAxisTickCountForWidth(chartWrapWidthPx)

  const lineChartMargin = useMemo(
    () => ({
      ...metricsChartMargin,
      bottom: xAxisBottomMarginForWidth(chartWrapWidthPx),
    }),
    [metricsChartMargin, chartWrapWidthPx],
  )

  const metricsTooltipContentStyle = useMemo(
    () =>
      ({
        backgroundColor: 'var(--color-background-elevated)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-button)',
        boxShadow: 'var(--shadow-panel)',
        padding: 'var(--spacing-2) var(--spacing-3)',
      }) as const,
    [],
  )

  const metricsTooltipLabelStyle = useMemo(
    () =>
      ({
        color: 'var(--color-text-primary)',
        fontWeight: 'var(--font-weight-semibold)',
      }) as const,
    [],
  )

  const metricsXAxisTick = useCallback(
    (props: Record<string, unknown>) => (
      <MetricsXAxisTick
        {...props}
        tickFill={chartColors.axisTick}
        tickFormatOptions={chartAxisTickFormatOptions}
      />
    ),
    [chartAxisTickFormatOptions, chartColors.axisTick],
  )

  const tooltipFormatter: NonNullable<TooltipProps['formatter']> = useCallback(
    (value, name, item) => {
      const dataKey =
        item && typeof item === 'object' && item !== null && 'dataKey' in item
          ? String((item as { dataKey?: unknown }).dataKey ?? '')
          : ''
      if (typeof value === 'number' && Number.isFinite(value)) {
        return [
          formatChartTooltipNumber(value, { metricKey, dataKey }),
          name ?? '',
        ]
      }
      return [value as ReactNode, (name ?? '') as ReactNode]
    },
    [metricKey],
  )

  return (
    <MetricsChartErrorBoundary key={chartResetKey}>
      <h2 className="metrics-chart__title">
        <span className="metrics-chart__title-line">{metricsChartTitleLines.line1}</span>
        <span className="metrics-chart__title-line">{metricsChartTitleLines.line2}</span>
      </h2>
      <div className="chart-wrap" ref={chartWrapRef}>
        <ResponsiveContainer width="100%" height={380}>
          <ComposedChart key={timeZone} data={chartData} margin={lineChartMargin}>
            <defs>
              <linearGradient id="metricAreaFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chartColors.primary} stopOpacity={0.22} />
                <stop offset="100%" stopColor={chartColors.primary} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="tMs"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              tickFormatter={formatAxisTimeLabel}
              tick={metricsXAxisTick}
              minTickGap={xAxisMinTickGap}
              tickCount={xAxisTickCount}
              label={{
                value: '時刻',
                position: 'bottom',
                offset: 10,
                style: { fill: chartColors.axisTick, fontSize: 11 },
              }}
            />
            <YAxis
              yAxisId="left"
              width={68}
              domain={[0, 'auto']}
              tick={{ fill: chartColors.axisTick }}
              tickFormatter={formatYAxisTickMetric}
              label={
                leftYAxisLabel
                  ? {
                      value: leftYAxisLabel,
                      angle: -90,
                      position: 'insideLeft',
                      style: { fill: chartColors.axisTick, fontSize: 11 },
                    }
                  : undefined
              }
            />
            <YAxis
              yAxisId="right"
              width={56}
              orientation="right"
              domain={[0, 'auto']}
              allowDecimals={false}
              tick={{ fill: chartColors.axisTick }}
              tickFormatter={formatYAxisTickCount}
              label={
                showEventLine
                  ? {
                      value: 'イベント件数',
                      angle: 90,
                      position: 'insideRight',
                      style: { fill: chartColors.axisTick, fontSize: 11 },
                    }
                  : undefined
              }
            />
            <Tooltip
              labelFormatter={formatTooltipLabel}
              formatter={tooltipFormatter}
              contentStyle={metricsTooltipContentStyle}
              labelStyle={metricsTooltipLabelStyle}
            />
            <Legend
              verticalAlign="top"
              align="right"
              wrapperStyle={{ paddingBottom: 6 }}
              onClick={onMetricsLegendClick}
            />
            {chartModel.mode === 'single' ? (
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="v"
                name={metricsChartLegendName}
                stroke={chartColors.primary}
                strokeWidth={2}
                fill="url(#metricAreaFill)"
                dot={false}
                activeDot={LINE_CHART_ACTIVE_DOT}
                isAnimationActive={false}
                hide={hiddenSeriesDataKeys.has('v')}
              />
            ) : (
              chartModel.metricSeries.map((s, i) => (
                <Line
                  key={s.dataKey}
                  yAxisId="left"
                  type="monotone"
                  dataKey={s.dataKey}
                  name={formatMetricChartSeriesLegendName(s, vcenterLabelForChart)}
                  stroke={chartColors.series[i % chartColors.series.length]}
                  strokeWidth={2}
                  connectNulls
                  dot={false}
                  activeDot={LINE_CHART_ACTIVE_DOT}
                  isAnimationActive={false}
                  hide={hiddenSeriesDataKeys.has(s.dataKey)}
                />
              ))
            )}
            {showEventLine && (
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="evCount"
                name={eventSeriesLegendName}
                stroke={chartColors.secondary}
                strokeWidth={2}
                dot={false}
                activeDot={LINE_CHART_ACTIVE_DOT}
                isAnimationActive={false}
                hide={hiddenSeriesDataKeys.has('evCount')}
              />
            )}
            {snapshotChartGuidelineMs != null && chartData.length > 0 ? (
              <ReferenceLine
                yAxisId="left"
                x={snapshotChartGuidelineMs}
                stroke="#c0392b"
                strokeDasharray="4 3"
                label={{
                  value: 'スナップショット',
                  position: 'top',
                  fill: chartColors.axisTick,
                  fontSize: 10,
                }}
              />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </MetricsChartErrorBoundary>
  )
}
