import type { IncidentTimeline } from '../../api/schemas'
import { IncidentTimelinePanel } from '../chat/IncidentTimelinePanel'

type TimelineResultsProps = {
  timeline: IncidentTimeline | null
  sortOrder: 'asc' | 'desc'
  snapshotMarkers: { timestamp_utc: string; label: string }[]
}

export function TimelineResults({ timeline, sortOrder, snapshotMarkers }: TimelineResultsProps) {
  if (timeline) {
    return (
      <IncidentTimelinePanel
        timeline={timeline}
        sortOrder={sortOrder}
        snapshotMarkers={snapshotMarkers}
      />
    )
  }

  return (
    <p className="hint">
      「タイムラインを生成」を押すと、指定期間のインシデント統合タイムラインを表示します。
    </p>
  )
}
