import { describe, expect, it } from 'vitest'

import { parseAlertTopN } from './timelineAlertTopNStorage'
import { buildSnapshotMarkersForTimeline } from './timelineSnapshotMarkers'

describe('timelineAlertTopNStorage', () => {
  it('parseAlertTopN は 1〜20 の整数のみ受理する', () => {
    expect(parseAlertTopN('7')).toBe(7)
    expect(parseAlertTopN('0')).toBeNull()
    expect(parseAlertTopN('21')).toBeNull()
    expect(parseAlertTopN('x')).toBeNull()
  })
})

describe('buildSnapshotMarkersForTimeline', () => {
  it('タイムライン列の min/max 内のスナップショットのみ返す', () => {
    const timeline = {
      columns: [
        { timestamp_utc: '2026-05-07T10:00:00Z', visible_items: [], hidden_count: 0 },
        { timestamp_utc: '2026-05-07T12:00:00Z', visible_items: [], hidden_count: 0 },
      ],
    }
    const markers = buildSnapshotMarkersForTimeline(timeline, [
      {
        snapshot_id: 'a',
        from: '2026-05-07T09:00:00Z',
        to: '2026-05-07T13:00:00Z',
        operator_note: 'in range',
        timestamp_utc: '2026-05-07T11:00:00Z',
        build_request_payload: { from: '2026-05-07T09:00:00Z', to: '2026-05-07T13:00:00Z' },
      },
      {
        snapshot_id: 'b',
        from: '2026-05-07T09:00:00Z',
        to: '2026-05-07T13:00:00Z',
        operator_note: 'out of range',
        timestamp_utc: '2026-05-07T08:00:00Z',
        build_request_payload: { from: '2026-05-07T09:00:00Z', to: '2026-05-07T13:00:00Z' },
      },
    ])
    expect(markers).toEqual([
      { timestamp_utc: '2026-05-07T11:00:00Z', label: 'in range' },
    ])
  })
})
