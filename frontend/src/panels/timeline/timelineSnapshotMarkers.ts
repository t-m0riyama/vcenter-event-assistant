import type { IncidentTimeline, IncidentTimelineManualSnapshotListItem } from '../../api/schemas'

/** タイムライン表示範囲内の手動スナップショットをマーカー用に抽出する。 */
export function buildSnapshotMarkersForTimeline(
  timeline: IncidentTimeline | null,
  items: IncidentTimelineManualSnapshotListItem[],
): { timestamp_utc: string; label: string }[] {
  if (!timeline?.columns.length) {
    return []
  }
  const times = timeline.columns.map((c) => new Date(c.timestamp_utc).getTime())
  const minT = Math.min(...times)
  const maxT = Math.max(...times)
  const out: { timestamp_utc: string; label: string }[] = []
  for (const item of items) {
    const t = new Date(item.timestamp_utc).getTime()
    if (!Number.isFinite(t)) {
      continue
    }
    if (t >= minT && t <= maxT) {
      out.push({ timestamp_utc: item.timestamp_utc, label: item.operator_note })
    }
  }
  return out
}
