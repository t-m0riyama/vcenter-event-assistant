import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { incidentTimelineManualSnapshotListItemSchema } from '../api/schemas'
import { useGraphRangeState, type MetricsSnapshotReplayInput } from './useGraphRangeState'

const item = incidentTimelineManualSnapshotListItemSchema.parse({
  snapshot_id: 'snapshot-1', operator_note: 'test',
  from: '2026-05-07T00:00:00Z', to: '2026-05-08T00:00:00Z',
  timestamp_utc: '2026-05-07T01:00:00Z',
  build_request_payload: { from: '2026-05-07T00:00:00Z', to: '2026-05-08T00:00:00Z' },
  graph_context: { captured_range: { from: '2026-05-07T02:00:00Z', to: '2026-05-07T03:00:00Z' } },
})

describe('useGraphRangeState', () => {
  it('recalculates rolling ranges and invalidates once on a timezone change, preserving manual edits', () => {
    const invalidate = vi.fn()
    const { result, rerender } = renderHook(({ tz }) => useGraphRangeState(tz, null, {
      onRollingRangeInvalidated: invalidate,
    }), { initialProps: { tz: 'UTC' } })
    const initial = result.current.rangeParts
    rerender({ tz: 'Asia/Tokyo' })
    expect(result.current.rangeParts).not.toEqual(initial)
    expect(invalidate).toHaveBeenCalledTimes(1)
    rerender({ tz: 'Asia/Tokyo' })
    expect(invalidate).toHaveBeenCalledTimes(1)
    const manual = { fromDate: '2026-01-01', fromTime: '12:00', toDate: '2026-01-02', toTime: '13:00' }
    act(() => result.current.onGraphRangeFieldsChange(manual))
    rerender({ tz: 'UTC' })
    expect(result.current.rangeParts).toEqual(manual)
    expect(invalidate).toHaveBeenCalledTimes(1)
  })

  it('applies captured ranges once, reapplies on a new replay nonce, and converts snapshot timezones', () => {
    const { result, rerender } = renderHook(
      ({ tz, replay }: { tz: string; replay: MetricsSnapshotReplayInput }) => useGraphRangeState(tz, replay),
      { initialProps: { tz: 'UTC', replay: { item, nonce: 1 } } },
    )
    expect(result.current.graphRangeFollowMode).toBe('manual')
    expect(result.current.rangeFromInput).toBe('2026-05-07T02:00')
    const expectedOverlay = result.current.graphRangeForOverlay
    const manual = { fromDate: '2026-01-01', fromTime: '12:00', toDate: '2026-01-02', toTime: '13:00' }
    act(() => result.current.onGraphRangeFieldsChange(manual))
    rerender({ tz: 'UTC', replay: { item, nonce: 1 } })
    expect(result.current.rangeParts).toEqual(manual)
    rerender({ tz: 'UTC', replay: { item, nonce: 2 } })
    expect(result.current.rangeFromInput).toBe('2026-05-07T02:00')
    rerender({ tz: 'Asia/Tokyo', replay: { item, nonce: 2 } })
    expect(result.current.rangeFromInput).toBe('2026-05-07T11:00')
    expect(result.current.graphRangeForOverlay).toEqual(expectedOverlay)
  })
})
