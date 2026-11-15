import { describe, expect, it } from 'vitest'

import type { TimelineViewItem } from '../../api/schemas'
import { DEFAULT_TIMELINE_CONDITIONS } from '../../routing/timelineHash'
import {
  anchorWindow,
  bucketRange,
  bucketStartContaining,
  buildViewRequest,
  correlationHashForItem,
  metricsFocusForItem,
  dragRange,
  formatDurationMs,
  isMetricOmitted,
  nearestItemIdToAnchor,
  omittedSourceMessages,
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
      sources: ['event', 'alert', 'metric', 'log'],
      metric_threshold_cpu_pct: 80,
      metric_threshold_memory_pct: 85,
    })
    expect(
      buildViewRequest({ ...DEFAULT_TIMELINE_CONDITIONS, cpuThresholdPct: 95, memoryThresholdPct: 60.5 }, range),
    ).toMatchObject({ metric_threshold_cpu_pct: 95, metric_threshold_memory_pct: 60.5 })
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

  it('グラフで開く条件は行の時刻の前後 30 分と vCenter と起点の目印。vCenter が無い行・読めない時刻は null', () => {
    expect(metricsFocusForItem(item('e', '2026-03-22T00:10:00', { vcenter_id: 'vc-1' }))).toEqual({
      from: '2026-03-21T23:40:00.000Z',
      to: '2026-03-22T00:40:00.000Z',
      vcenterId: 'vc-1',
      markerUtc: '2026-03-22T00:10:00.000Z',
    })
    // まとめた行は最初の時刻の 30 分前から end_utc の 30 分後まで。目印は最初の時刻
    expect(
      metricsFocusForItem(
        item('m', '2026-03-22T00:10:00Z', { vcenter_id: 'vc-1', count: 3, end_utc: '2026-03-22T00:50:00' }),
      ),
    ).toMatchObject({ from: '2026-03-21T23:40:00.000Z', to: '2026-03-22T01:20:00.000Z', markerUtc: '2026-03-22T00:10:00.000Z' })
    // metric のアラートは指標、イベントはイベント種別を渡す（それ以外の種別・値は渡さない）
    expect(
      metricsFocusForItem(item('a', '2026-03-22T00:10:00Z', { kind: 'alert', vcenter_id: 'vc-1', ref: { metric_key: 'host.mem.usage_pct' } })),
    ).toMatchObject({ metricKey: 'host.mem.usage_pct' })
    expect(
      metricsFocusForItem(item('v', '2026-03-22T00:10:00Z', { kind: 'event', vcenter_id: 'vc-1', ref: { event_type: 'VmPoweredOffEvent' } })),
    ).toMatchObject({ chartEventType: 'VmPoweredOffEvent' })
    const plain = metricsFocusForItem(item('p', '2026-03-22T00:10:00Z', { vcenter_id: 'vc-1' }))!
    expect(plain.metricKey).toBeUndefined()
    expect(plain.chartEventType).toBeUndefined()
    expect(metricsFocusForItem(item('x', '2026-03-22T00:10:00Z'))).toBeNull()
    expect(metricsFocusForItem(item('y', 'broken', { vcenter_id: 'vc-1' }))).toBeNull()
  })

  it('グラフで開く条件（メトリクスの行）: 開始の 30 分前から終了の 30 分後、指標は ref.metric_key、縦線はピークの時刻', () => {
    const base = {
      kind: 'metric' as const,
      vcenter_id: 'vc-1',
      end_utc: '2026-03-22T00:15:00Z',
      ref: { metric_key: 'host.cpu.usage_pct', peak_at_utc: '2026-03-22T00:10:00Z' },
    }
    expect(metricsFocusForItem(item('m', '2026-03-22T00:05:00Z', base))).toEqual({
      from: '2026-03-21T23:35:00.000Z',
      to: '2026-03-22T00:45:00.000Z',
      vcenterId: 'vc-1',
      markerUtc: '2026-03-22T00:10:00.000Z',
      metricKey: 'host.cpu.usage_pct',
    })
    // ピークの時刻が無ければ区間の開始。単発（end_utc なし）は開始の前後 30 分
    expect(
      metricsFocusForItem(item('m', '2026-03-22T00:05:00Z', { ...base, end_utc: null, ref: { metric_key: 'host.mem.usage_pct' } })),
    ).toEqual({
      from: '2026-03-21T23:35:00.000Z',
      to: '2026-03-22T00:35:00.000Z',
      vcenterId: 'vc-1',
      markerUtc: '2026-03-22T00:05:00.000Z',
      metricKey: 'host.mem.usage_pct',
    })
    // 読めないピークの時刻は使わない
    expect(
      metricsFocusForItem(item('m', '2026-03-22T00:05:00Z', { ...base, ref: { metric_key: 'k', peak_at_utc: 'broken' } }))?.markerUtc,
    ).toBe('2026-03-22T00:05:00.000Z')
  })

  it('グラフで開く条件: ログの行は指標が無いので出さない（null）', () => {
    expect(metricsFocusForItem(item('l', '2026-03-22T00:10:00Z', { kind: 'log', vcenter_id: 'vc-1' }))).toBeNull()
  })

  it('ログで開くリンクは、最初の時刻の 5 分前から最後の時刻の 5 分後まで', () => {
    const link = correlationHashForItem(
      'logs',
      item('l', '2026-03-22T01:00:00Z', { kind: 'log', vcenter_id: 'vc-1', count: 2, end_utc: '2026-03-22T01:01:00Z' }),
    )!
    const params = new URLSearchParams(link.split('?')[1])
    expect(params.get('from')).toBe('2026-03-22T00:55:00.000Z')
    expect(params.get('to')).toBe('2026-03-22T01:06:00.000Z')
  })

  it('継続時間は秒・分・時間・日で人が読める形にする', () => {
    expect(formatDurationMs(0)).toBe('0 秒')
    expect(formatDurationMs(45_000)).toBe('45 秒')
    expect(formatDurationMs(60_000)).toBe('1 分')
    expect(formatDurationMs(10 * 60_000)).toBe('10 分')
    expect(formatDurationMs(65 * 60_000)).toBe('1 時間 5 分')
    expect(formatDurationMs(2 * 3_600_000)).toBe('2 時間')
    expect(formatDurationMs(27 * 3_600_000)).toBe('1 日 3 時間')
    expect(formatDurationMs(48 * 3_600_000)).toBe('2 日')
    expect(formatDurationMs(-5)).toBe('0 秒')
  })

  it('省いた種別の知らせ: ログは「件数は上のグラフに出ている」、メトリクスは「グラフにも出ていない」', () => {
    expect(omittedSourceMessages([])).toEqual([])
    const [log] = omittedSourceMessages([{ source: 'log', reason: 'too_many_rows' }])
    expect(log).toContain('ログは件数が多すぎるため、一覧から省いています')
    expect(log).toContain('件数は上のグラフに出ています')
    const [metric] = omittedSourceMessages([{ source: 'metric', reason: 'too_many_rows' }])
    expect(metric).toContain('メトリクスの超過区間')
    expect(metric).toContain('グラフにも出ていません')
    expect(
      omittedSourceMessages([
        { source: 'metric', reason: 'too_many_rows' },
        { source: 'log', reason: 'too_many_rows' },
      ]),
    ).toHaveLength(2)
    // 知らない種別・理由も黙って捨てず、種別名つきで知らせる
    expect(omittedSourceMessages([{ source: 'other', reason: 'x' }])[0]).toContain('other')
  })

  it('メトリクスを省いたかは omitted_sources から判定する', () => {
    expect(isMetricOmitted([])).toBe(false)
    expect(isMetricOmitted([{ source: 'log', reason: 'too_many_rows' }])).toBe(false)
    expect(isMetricOmitted([{ source: 'metric', reason: 'too_many_rows' }])).toBe(true)
  })
})
