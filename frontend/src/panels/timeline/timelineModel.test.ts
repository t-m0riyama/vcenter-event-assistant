import { describe, expect, it } from 'vitest'

import type { TimelineViewItem } from '../../api/schemas'
import { DEFAULT_TIMELINE_CONDITIONS } from '../../routing/timelineHash'
import {
  anchorWindow,
  bucketRange,
  bucketStartContaining,
  buildViewRequest,
  correlationHashForItem,
  dragRange,
  nearestItemIdToAnchor,
  resolveTimelineRange,
  sortTimelineItems,
  validateResolvedRange,
  widenRange,
} from './timelineModel'

function item(id: string, ts: string, extra: Partial<TimelineViewItem> = {}): TimelineViewItem {
  return { id, kind: 'event', timestamp_utc: ts, level: 'info', title: id, count: 1, ref: {}, ...extra }
}

describe('timelineModel', () => {
  it('直近 N 時間は今を終わりに解決し、固定はそのまま', () => {
    const now = Date.parse('2026-03-22T01:00:00Z')
    expect(resolveTimelineRange({ mode: 'rolling', durationMs: 3_600_000 }, now)).toEqual({
      from: '2026-03-22T00:00:00.000Z',
      to: '2026-03-22T01:00:00.000Z',
    })
    expect(resolveTimelineRange({ mode: 'fixed', from: 'a', to: 'b' }, now)).toEqual({ from: 'a', to: 'b' })
  })

  it('期間の検証: 逆順・同じ秒・90 日超を断る', () => {
    expect(validateResolvedRange({ from: '2026-03-22T00:00:00Z', to: '2026-03-22T00:00:00.900Z' })).toMatch('前')
    expect(validateResolvedRange({ from: '2026-03-22T01:00:00Z', to: '2026-03-22T00:00:00Z' })).toMatch('前')
    expect(validateResolvedRange({ from: '2026-01-01T00:00:00Z', to: '2026-04-02T00:00:00Z' })).toMatch('90')
    expect(validateResolvedRange({ from: '2026-03-22T00:00:00Z', to: '2026-03-22T00:00:01Z' })).toBeNull()
  })

  it('棒の範囲は開始 + バケット幅。最後の棒は期間の終わりで切る', () => {
    expect(bucketRange('2026-03-22T00:10:00Z', 60, '2026-03-22T01:00:00Z')).toEqual({
      from: '2026-03-22T00:10:00.000Z',
      to: '2026-03-22T00:11:00.000Z',
    })
    expect(bucketRange('2026-03-22T00:59:00Z', 120, '2026-03-22T01:00:30Z').to).toBe('2026-03-22T01:00:30.000Z')
  })

  it('ドラッグの範囲は始点・終点の順不同で、終点の棒の終わりまで', () => {
    const r = dragRange('2026-03-22T00:30:00Z', '2026-03-22T00:10:00Z', 300, '2026-03-22T01:00:00Z')
    expect(r).toEqual({ from: '2026-03-22T00:10:00.000Z', to: '2026-03-22T00:35:00.000Z' })
  })

  it('起点を中心にした前後の範囲', () => {
    expect(anchorWindow('2026-03-22T01:00:00Z', 900_000)).toEqual({
      from: '2026-03-22T00:45:00.000Z',
      to: '2026-03-22T01:15:00.000Z',
    })
  })

  it('期間を広げる: 直近は終わりを保って前へ、固定は前後へ、上限は 90 日', () => {
    const cur = { from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T01:00:00.000Z' }
    expect(widenRange(cur, { mode: 'rolling', durationMs: 3_600_000 })).toEqual({
      from: '2026-03-21T23:00:00.000Z',
      to: '2026-03-22T01:00:00.000Z',
    })
    expect(widenRange(cur, { mode: 'fixed', ...cur })).toEqual({
      from: '2026-03-21T23:30:00.000Z',
      to: '2026-03-22T01:30:00.000Z',
    })
    const huge = widenRange({ from: '2026-01-01T00:00:00.000Z', to: '2026-03-30T00:00:00.000Z' }, { mode: 'fixed', from: '', to: '' })
    expect(validateResolvedRange(huge)).toBeNull()
  })

  it('起点に最も近い行（区間は区間までの距離）。起点が無ければ null', () => {
    const items = [
      item('a', '2026-03-22T00:10:00Z'),
      item('b', '2026-03-22T00:20:00Z', { end_utc: '2026-03-22T00:40:00Z', count: 3 }),
      item('c', '2026-03-22T00:55:00Z'),
    ]
    expect(nearestItemIdToAnchor(items, '2026-03-22T00:30:00Z')).toBe('b')
    expect(nearestItemIdToAnchor(items, '2026-03-22T00:50:00Z')).toBe('c')
    expect(nearestItemIdToAnchor(items, null)).toBeNull()
    expect(nearestItemIdToAnchor([], '2026-03-22T00:30:00Z')).toBeNull()
  })

  it('起点を含む棒を探す', () => {
    const buckets = ['00:00', '00:10', '00:20'].map((t) => ({
      bucket_start_utc: `2026-03-22T${t}:00Z`,
      event_total: 0,
      event_notable: 0,
      alert: 0,
      metric_breach: 0,
      log_error: 0,
    }))
    expect(bucketStartContaining(buckets, 600, '2026-03-22T00:14:59Z')).toBe('2026-03-22T00:10:00Z')
    expect(bucketStartContaining(buckets, 600, '2026-03-22T01:00:00Z')).toBeNull()
  })

  it('並び順: asc は API のまま、desc は反転（元の配列は変えない）', () => {
    const items = [item('a', '2026-03-22T00:00:00Z'), item('b', '2026-03-22T00:01:00Z')]
    expect(sortTimelineItems(items, 'asc').map((i) => i.id)).toEqual(['a', 'b'])
    expect(sortTimelineItems(items, 'desc').map((i) => i.id)).toEqual(['b', 'a'])
    expect(items.map((i) => i.id)).toEqual(['a', 'b'])
  })

  it('API 本文は設定した条件だけを載せる', () => {
    const range = { from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T01:00:00.000Z' }
    expect(buildViewRequest(DEFAULT_TIMELINE_CONDITIONS, range)).toEqual({
      ...range,
      min_score: 1,
      sources: ['event', 'alert'],
    })
    expect(
      buildViewRequest(
        { ...DEFAULT_TIMELINE_CONDITIONS, anchor: '2026-03-22T00:30:00.000Z', vcenterId: 'vc', entity: 'esx', sources: ['alert'] },
        range,
      ),
    ).toMatchObject({ anchor: '2026-03-22T00:30:00.000Z', vcenter_id: 'vc', entity: 'esx', sources: ['alert'] })
  })

  it('イベント・ログで開くリンクは行の時刻の前後 5 分と vCenter。vCenter が無ければ null', () => {
    const it1 = item('e', '2026-03-22T00:10:00', { vcenter_id: 'vc-1' })
    const link = correlationHashForItem('events', it1)!
    expect(link.startsWith('#/events?')).toBe(true)
    const params = new URLSearchParams(link.split('?')[1])
    expect(params.get('vcenter_id')).toBe('vc-1')
    expect(params.get('from')).toBe('2026-03-22T00:05:00.000Z')
    expect(params.get('to')).toBe('2026-03-22T00:15:00.000Z')
    expect(correlationHashForItem('logs', item('x', '2026-03-22T00:10:00Z'))).toBeNull()
  })
})
