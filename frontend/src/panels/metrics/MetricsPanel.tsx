import { useCallback, useLayoutEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  type TooltipProps,
  XAxis,
  YAxis,
} from 'recharts'
import {
  buildMetricsExportBasename,
  downloadChartSvg,
} from '../../metrics/downloadChartSvg'
import { downloadMetricPointsCsv } from '../../metrics/metricCsv'
import { MetricsChartErrorBoundary } from '../../metrics/MetricsChartErrorBoundary'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { summarizeGraphRangePreview } from '../../datetime/graphRange'
import { toErrorMessage } from '../../utils/errors'
import { useIntervalWhenEnabled } from '../../hooks/useIntervalWhenEnabled'
import { useMetricsPanelController } from '../../hooks/useMetricsPanelController'
import { useAutoRefreshPreferences } from '../../preferences/useAutoRefreshPreferences'
import { formatChartTooltipNumber } from '../../metrics/chartYAxisFormat'
import {
  xAxisBottomMarginForWidth,
  xAxisMinTickGapForWidth,
  xAxisTickCountForWidth,
} from './chartXAxisLayout'
import { MetricsXAxisTick } from './MetricsXAxisTick'

const LINE_CHART_DATA_DOT = { r: 3, strokeWidth: 1 } as const

export function MetricsPanel({
  onError,
  perfBucketSeconds,
}: {
  onError: (e: string | null) => void
  perfBucketSeconds: number
}) {
  const {
    timeZone,
    vcenters,
    vcenterId,
    setVcenterId,
    metricKeys,
    metricKey,
    setMetricKey,
    points,
    metricTotal,
    loading,
    chartResetKey,
    setChartResetKey,
    chartEventType,
    setChartEventType,
    eventTypeOptions,
    rangeParts,
    setRangeParts,
    chartWrapRef,
    chartColors,
    invalidateSeriesCache,
    load,
    showEventLine,
    leftYAxisLabel,
    metricsChartMargin,
    chartModel,
    chartData,
    vcenterLabelForChart,
    metricsChartTitleLines,
    metricsChartLegendName,
    eventSeriesLegendName,
    chartAxisTickFormatOptions,
    formatAxisTimeLabel,
    formatYAxisTickMetric,
    formatYAxisTickCount,
    vcenterExportLabel,
    exportDisabled,
    csvExportOptions,
  } = useMetricsPanelController(onError, perfBucketSeconds)

  const { autoRefreshEnabled, autoRefreshIntervalMinutes } = useAutoRefreshPreferences()
  const intervalMs = useMemo(
    () => autoRefreshIntervalMinutes * 60_000,
    [autoRefreshIntervalMinutes],
  )
  const onAutoRefreshMetrics = useCallback(() => {
    invalidateSeriesCache()
    void load(metricKey, { silent: true })
  }, [invalidateSeriesCache, load, metricKey])
  useIntervalWhenEnabled(autoRefreshEnabled, intervalMs, onAutoRefreshMetrics)

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

  const downloadSvg = () => {
    try {
      const base = buildMetricsExportBasename(vcenterId, vcenterExportLabel, metricKey)
      downloadChartSvg(chartWrapRef.current, `${base}.svg`, {
        lines: [metricsChartTitleLines.line1, metricsChartTitleLines.line2],
      })
      onError(null)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const downloadCsv = () => {
    try {
      const base = buildMetricsExportBasename(vcenterId, vcenterExportLabel, metricKey)
      downloadMetricPointsCsv(points, `${base}.csv`, csvExportOptions)
      onError(null)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  return (
    <div className="panel">
      <div className="toolbar">
        <label>
          vCenter
          <select value={vcenterId} onChange={(e) => setVcenterId(e.target.value)}>
            <option value="">全て</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          メトリクスキー
          <select
            value={metricKey}
            disabled={metricKeys.length === 0}
            onChange={(e) => setMetricKey(e.target.value)}
          >
            {metricKeys.length === 0 ? (
              <option value="">メトリクスキーがありません</option>
            ) : (
              metricKeys.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))
            )}
          </select>
        </label>
        <label>
          イベント種別（任意・完全一致）
          <input
            type="text"
            value={chartEventType}
            onChange={(e) => setChartEventType(e.target.value)}
            list="metrics-event-type-options"
            placeholder="例: VmPoweredOnEvent"
            autoComplete="off"
          />
          <datalist id="metrics-event-type-options">
            {eventTypeOptions.map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
        <button
          type="button"
          className="btn btn--filled"
          disabled={loading || !metricKey}
          onClick={() => {
            setChartResetKey((k) => k + 1)
            invalidateSeriesCache()
            void load(metricKey)
          }}
        >
          {loading ? '取得中…' : '再取得'}
        </button>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exportDisabled}
          onClick={downloadSvg}
        >
          グラフをダウンロード
        </button>
        <button
          type="button"
          className="btn btn--gray"
          disabled={exportDisabled}
          onClick={downloadCsv}
        >
          CSV をダウンロード
        </button>
        {metricTotal !== null && !loading && (
          <span className="metric-total">
            条件一致: {metricTotal} 件（表示: {points.length} 件まで）
          </span>
        )}
      </div>
      <details className="toolbar__filters-details metrics-panel__range-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">表示期間</span>
          <span className="toolbar__filters-summary__preview">
            {summarizeGraphRangePreview(rangeParts)}
          </span>
        </summary>
        <p className="hint toolbar__filters-hint">
          表示期間は「設定 → 一般」のタイムゾーン上の壁時計です。開始・終了は両方指定するか、すべて空にしてください。日付のみの場合は開始は
          0:00・終了は 23:59 です。期間を指定するとメトリクスは最大 10000
          点まで取得し、イベント件数オーバーレイも同じ区間で集計します。
        </p>
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </details>
      <p className="hint">
        イベント件数はサーバ設定のメトリクス取得間隔（{perfBucketSeconds}
        秒）と同じ幅のバケットに集計されます。種別を空にするとメトリクスのみ表示します。
      </p>
      {!loading && metricKeys.length === 0 && (
        <p className="hint">
          この条件で DB に保存されたメトリクスがありません。スケジュール取り込みを待ってから再度開いてください。
        </p>
      )}
      {!loading && metricTotal === 0 && metricKey && (
        <div className="empty-metrics">
          <p>該当するメトリクスがありません（条件一致 0 件）。</p>
          <ul>
            <li>vCenter の「有効」がオンか確認してください。</li>
            <li>初回は数分待ってから「再取得」してください。</li>
            <li>接続情報・権限が正しいか、接続テストで確認してください。</li>
          </ul>
        </div>
      )}
      <MetricsChartErrorBoundary key={`${vcenterId}-${metricKey}-${chartResetKey}`}>
        <h2 className="metrics-chart__title">
          <span className="metrics-chart__title-line">{metricsChartTitleLines.line1}</span>
          <span className="metrics-chart__title-line">{metricsChartTitleLines.line2}</span>
        </h2>
        <div className="chart-wrap" ref={chartWrapRef}>
          <ResponsiveContainer width="100%" height={380}>
            <LineChart key={timeZone} data={chartData} margin={lineChartMargin}>
              <CartesianGrid stroke={chartColors.grid} strokeDasharray="3 3" />
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
                labelFormatter={formatAxisTimeLabel}
                formatter={tooltipFormatter}
              />
              <Legend
                verticalAlign="top"
                align="right"
                wrapperStyle={{ paddingBottom: 6 }}
              />
              {chartModel.mode === 'single' ? (
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="v"
                  name={metricsChartLegendName}
                  stroke={chartColors.primary}
                  dot={LINE_CHART_DATA_DOT}
                  isAnimationActive={false}
                />
              ) : (
                chartModel.metricSeries.map((s, i) => (
                  /* エンティティ別の欠損時刻は未採取（0 ではない）。直前の点から次の点へ線でつなぐ */
                  <Line
                    key={s.dataKey}
                    yAxisId="left"
                    type="monotone"
                    dataKey={s.dataKey}
                    name={`${vcenterLabelForChart} / ${s.legendName}`}
                    stroke={chartColors.series[i % chartColors.series.length]}
                    connectNulls
                    dot={LINE_CHART_DATA_DOT}
                    isAnimationActive={false}
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
                  dot={LINE_CHART_DATA_DOT}
                  isAnimationActive={false}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </MetricsChartErrorBoundary>
    </div>
  )
}
