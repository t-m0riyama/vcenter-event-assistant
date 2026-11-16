import { describe, expect, it } from 'vitest'

import {
  incidentTimelineManualSnapshotCreateRequestSchema,
  incidentTimelineManualSnapshotDetailSchema,
  incidentTimelineManualSnapshotListItemSchema,
} from '.'
import { emptyViewResponse } from '../../test/timelineViewFixtures'

const base = {
  snapshot_id: 's1',
  from: '2026-03-10T00:00:00Z',
  to: '2026-03-10T03:00:00Z',
  operator_note: 'memo',
  timestamp_utc: '2026-03-10T03:30:00Z',
  build_request_payload: { from: '2026-03-10T00:00:00Z', to: '2026-03-10T03:00:00Z' },
}

describe('スナップショットの結果保存のスキーマ', () => {
  it('旧データの一覧項目は has_result が false、view_request が無い', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse(base)
    expect(item.has_result).toBe(false)
    expect(item.view_request ?? null).toBeNull()
  })

  it('読めない形の view_request は null として扱い、一覧全体を壊さない', () => {
    const item = incidentTimelineManualSnapshotListItemSchema.parse({ ...base, has_result: true, view_request: { x: 1 } })
    expect(item.view_request).toBeNull()
  })

  it('詳細は結果を持ち、読めない形の結果は null になる', () => {
    const ok = incidentTimelineManualSnapshotDetailSchema.parse({ ...base, has_result: true, result: emptyViewResponse() })
    expect(ok.result?.total_items).toBe(0)
    const drifted = incidentTimelineManualSnapshotDetailSchema.parse({ ...base, has_result: true, result: { legacy: 1 } })
    expect(drifted.result).toBeNull()
  })

  it('保存のリクエストは view_request を持てるが、結果は送れない', () => {
    const body = { from: base.from, to: base.to, timestamp_utc: base.timestamp_utc, operator_note: 'm' }
    expect(
      incidentTimelineManualSnapshotCreateRequestSchema.parse({ ...body, view_request: { from: base.from, to: base.to } })
        .view_request,
    ).toEqual({ from: base.from, to: base.to })
    expect(() => incidentTimelineManualSnapshotCreateRequestSchema.parse({ ...body, result: {} })).toThrow()
  })
})
