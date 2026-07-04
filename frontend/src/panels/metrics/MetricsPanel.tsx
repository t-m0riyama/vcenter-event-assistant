import { useMemo } from 'react'
import './MetricsPanel.css'

import {
  buildMetricsExportBasename,
  downloadChartSvg,
} from '../../metrics/export/downloadChartSvg'
import { downloadMetricPointsCsv } from '../../metrics/metricCsv'
import { toErrorMessage } from '../../utils/errors'
import { useIntervalWhenEnabled } from '../../hooks/useIntervalWhenEnabled'
import {
  useMetricsPanelController,
  type MetricsSnapshotReplayInput,
} from '../../hooks/useMetricsPanelController'
import { useAutoRefreshPreferences } from '../../preferences/useAutoRefreshPreferences'
import { MetricsChart } from './MetricsChart'
import { MetricsRangeFields } from './MetricsRangeFields'
import { MetricsToolbar } from './MetricsToolbar'

/** メトリクスグラフパネル（期間・系列・CSV/SVG export）。 */
export function MetricsPanel({
  onError,
  perfBucketSeconds,
  snapshotReplay,
}: {
  onError: (e: string | null) => void
  perfBucketSeconds: number
  snapshotReplay?: MetricsSnapshotReplayInput | null
}) {
  const controller = useMetricsPanelController(onError, perfBucketSeconds, snapshotReplay ?? null)
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
    onGraphRangeFieldsChange,
    applyRollingPreset,
    chartWrapRef,
    chartColors,
    runMetricsAutoRefresh,
    reloadMetricsSeries,
    showEventLine,
    leftYAxisLabel,
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
    graphRangeDisplayLabel,
    vcenterExportLabel,
    exportDisabled,
    csvExportOptions,
    snapshotChartGuidelineMs,
  } = controller

  const {
    autoRefreshEnabled,
    setAutoRefreshEnabled,
    autoRefreshIntervalMinutes,
  } = useAutoRefreshPreferences()
  const intervalMs = useMemo(
    () => autoRefreshIntervalMinutes * 60_000,
    [autoRefreshIntervalMinutes],
  )
  useIntervalWhenEnabled(autoRefreshEnabled, intervalMs, runMetricsAutoRefresh)

  const chartResetBoundaryKey = `${vcenterId}-${metricKey}-${chartResetKey}`

  const handleReload = () => {
    setChartResetKey((k) => k + 1)
    reloadMetricsSeries()
  }

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
      <MetricsToolbar
        vcenters={vcenters}
        vcenterId={vcenterId}
        setVcenterId={setVcenterId}
        metricKeys={metricKeys}
        metricKey={metricKey}
        setMetricKey={setMetricKey}
        chartEventType={chartEventType}
        setChartEventType={setChartEventType}
        eventTypeOptions={eventTypeOptions}
        loading={loading}
        exportDisabled={exportDisabled}
        metricTotal={metricTotal}
        pointsCount={points.length}
        onReload={handleReload}
        onDownloadSvg={downloadSvg}
        onDownloadCsv={downloadCsv}
      />
      <MetricsRangeFields
        graphRangeDisplayLabel={graphRangeDisplayLabel}
        autoRefreshEnabled={autoRefreshEnabled}
        setAutoRefreshEnabled={setAutoRefreshEnabled}
        autoRefreshIntervalMinutes={autoRefreshIntervalMinutes}
        rangeParts={rangeParts}
        onGraphRangeFieldsChange={onGraphRangeFieldsChange}
        applyRollingPreset={applyRollingPreset}
      />
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
      <MetricsChart
        chartResetKey={chartResetBoundaryKey}
        timeZone={timeZone}
        metricKey={metricKey}
        chartWrapRef={chartWrapRef}
        chartColors={chartColors}
        metricsChartMargin={metricsChartMargin}
        chartModel={chartModel}
        chartData={chartData}
        hiddenSeriesDataKeys={hiddenSeriesDataKeys}
        onMetricsLegendClick={onMetricsLegendClick}
        vcenterLabelForChart={vcenterLabelForChart}
        metricsChartTitleLines={metricsChartTitleLines}
        metricsChartLegendName={metricsChartLegendName}
        eventSeriesLegendName={eventSeriesLegendName}
        chartAxisTickFormatOptions={chartAxisTickFormatOptions}
        formatAxisTimeLabel={formatAxisTimeLabel}
        formatTooltipLabel={formatTooltipLabel}
        formatYAxisTickMetric={formatYAxisTickMetric}
        formatYAxisTickCount={formatYAxisTickCount}
        showEventLine={showEventLine}
        leftYAxisLabel={leftYAxisLabel}
        snapshotChartGuidelineMs={snapshotChartGuidelineMs}
      />
    </div>
  )
}
