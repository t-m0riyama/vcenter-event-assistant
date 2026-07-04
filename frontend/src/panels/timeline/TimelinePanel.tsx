import './TimelinePanel.css'

import type { IncidentTimelineManualSnapshotListItem } from '../../api/schemas'
import { useTimelinePanelController } from '../../hooks/useTimelinePanelController'
import { TimelineFilters } from './TimelineFilters'
import { TimelineResults } from './TimelineResults'
import { TimelineSnapshotActions } from './TimelineSnapshotActions'

/** インシデントタイムライン生成・表示パネル。 */
export function TimelinePanel({
  onError,
  onOpenSnapshotInMetrics,
}: {
  onError: (e: string | null) => void
  onOpenSnapshotInMetrics?: (item: IncidentTimelineManualSnapshotListItem) => void
}) {
  const c = useTimelinePanelController(onError)

  return (
    <div className="panel timeline-panel">
      <TimelineFilters
        rangeParts={c.rangeParts}
        setRangeParts={c.setRangeParts}
        vcenters={c.vcenters}
        vcenterId={c.vcenterId}
        setVcenterId={c.setVcenterId}
        loading={c.loading}
        includePeriodMetricsCpu={c.includePeriodMetricsCpu}
        setIncludePeriodMetricsCpu={c.setIncludePeriodMetricsCpu}
        includePeriodMetricsMemory={c.includePeriodMetricsMemory}
        setIncludePeriodMetricsMemory={c.setIncludePeriodMetricsMemory}
        includePeriodMetricsDiskIo={c.includePeriodMetricsDiskIo}
        setIncludePeriodMetricsDiskIo={c.setIncludePeriodMetricsDiskIo}
        includePeriodMetricsNetworkIo={c.includePeriodMetricsNetworkIo}
        setIncludePeriodMetricsNetworkIo={c.setIncludePeriodMetricsNetworkIo}
        metricThresholdCpuInput={c.metricThresholdCpuInput}
        metricThresholdCpuPct={c.metricThresholdCpuPct}
        setMetricThresholdCpuInput={c.setMetricThresholdCpuInput}
        setMetricThresholdCpuPct={c.setMetricThresholdCpuPct}
        metricThresholdMemoryInput={c.metricThresholdMemoryInput}
        metricThresholdMemoryPct={c.metricThresholdMemoryPct}
        setMetricThresholdMemoryInput={c.setMetricThresholdMemoryInput}
        setMetricThresholdMemoryPct={c.setMetricThresholdMemoryPct}
        metricThresholdDiskInput={c.metricThresholdDiskInput}
        metricThresholdDiskPct={c.metricThresholdDiskPct}
        setMetricThresholdDiskInput={c.setMetricThresholdDiskInput}
        setMetricThresholdDiskPct={c.setMetricThresholdDiskPct}
        metricThresholdNetworkInput={c.metricThresholdNetworkInput}
        metricThresholdNetworkPct={c.metricThresholdNetworkPct}
        setMetricThresholdNetworkInput={c.setMetricThresholdNetworkInput}
        setMetricThresholdNetworkPct={c.setMetricThresholdNetworkPct}
        alertTopNInput={c.alertTopNInput}
        alertTopN={c.alertTopN}
        setAlertTopNInput={c.setAlertTopNInput}
        setAlertTopN={c.setAlertTopN}
        sortOrder={c.sortOrder}
        setSortOrder={c.setSortOrder}
        onMetricThresholdInputChange={c.handleMetricThresholdInputChange}
        onAlertTopNInputChange={c.handleAlertTopNInputChange}
        onAlertTopNBlur={c.handleAlertTopNBlur}
      />

      <TimelineSnapshotActions
        loading={c.loading}
        savingSnapshot={c.savingSnapshot}
        hasTimeline={c.timeline != null}
        operatorNote={c.operatorNote}
        setOperatorNote={c.setOperatorNote}
        onGenerateTimeline={c.generateTimeline}
        onSaveSnapshot={c.saveManualSnapshot}
        manualSnapshotAuditItems={c.manualSnapshotAuditItems}
        selectedManualSnapshotId={c.selectedManualSnapshotId}
        setSelectedManualSnapshotId={c.setSelectedManualSnapshotId}
        onLoadTimelineFromSnapshot={c.loadTimelineFromSnapshot}
        onOpenSnapshotInMetrics={onOpenSnapshotInMetrics}
      />

      <TimelineResults
        timeline={c.timeline}
        sortOrder={c.sortOrder}
        snapshotMarkers={c.snapshotMarkers}
      />
    </div>
  )
}
