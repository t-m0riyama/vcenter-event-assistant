import { apiGet } from '../api'
import {
  incidentTimelineManualSnapshotDetailSchema,
  type IncidentTimelineManualSnapshotDetail,
} from './schemas'

/** `GET /api/incident-timeline/snapshots/manual/{id}`: 保存時点の結果つきで 1 件を取得する。 */
export async function getManualSnapshotDetail(snapshotId: string): Promise<IncidentTimelineManualSnapshotDetail> {
  const raw = await apiGet<unknown>(`/api/incident-timeline/snapshots/manual/${encodeURIComponent(snapshotId)}`)
  return incidentTimelineManualSnapshotDetailSchema.parse(raw)
}
