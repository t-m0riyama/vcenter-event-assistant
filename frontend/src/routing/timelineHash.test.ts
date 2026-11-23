/** @vitest-environment happy-dom */
import { describe, expect, it } from 'vitest'

import { correlationHash, readCorrelationRange } from './correlationRange'
import {
  buildTimelineHash,
  timelineEntryHash,
  DEFAULT_TIMELINE_CONDITIONS,
  parseTimelineHash,
  readTimelineHash,
  replaceTimelineHash,
  type TimelineConditions,
} from './timelineHash'

const FIXED: TimelineConditions = {
  range: { mode: 'fixed', from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T01:30:00.000Z' },
  anchor: '2026-03-22T00:40:00.000Z',
  vcenterId: '11111111-1111-4111-8111-111111111111',
  entity: 'esx 01',
  entityMoid: 'host-10',
  minScore: 40,
  sources: ['alert'],
  cpuThresholdPct: 90,
  memoryThresholdPct: 72.5,
}

describe('timelineHash', () => {
  it('固定の期間と全条件を往復できる', () => {
    const hash = buildTimelineHash(FIXED)
    expect(hash).toContain('from=2026-03-22T00%3A00%3A00.000Z')
    expect(hash).toContain('entity_moid=host-10')
    expect(parseTimelineHash(hash)).toEqual({ conditions: FIXED, issue: null })
  })

  it('直近 N 時間は from / to を固定せず range=1h で表し、開き直すと直近 N 時間に戻る', () => {
    const hash = buildTimelineHash({ ...DEFAULT_TIMELINE_CONDITIONS, range: { mode: 'rolling', durationMs: 6 * 3_600_000 } })
    expect(hash).toBe('#/timeline?range=6h')
    expect(hash).not.toContain('from=')
    expect(parseTimelineHash(hash)?.conditions.range).toEqual({ mode: 'rolling', durationMs: 6 * 3_600_000 })
  })

  it('既定値の項目は省略する', () => {
    expect(buildTimelineHash(DEFAULT_TIMELINE_CONDITIONS)).toBe('#/timeline?range=1h')
  })

  it('クエリが無い・タイムライン以外のハッシュは null', () => {
    expect(parseTimelineHash('#/timeline')).toBeNull()
    expect(parseTimelineHash('#/events?range=1h')).toBeNull()
  })

  it('逆順の期間・片方だけの期間・不正な値は黙って既定にせず、理由（issue）を返す', () => {
    const reversed = parseTimelineHash('#/timeline?from=2026-03-22T02:00:00Z&to=2026-03-22T01:00:00Z')
    expect(reversed?.issue).toContain('開始')
    expect(reversed?.conditions.range).toEqual(DEFAULT_TIMELINE_CONDITIONS.range)
    expect(parseTimelineHash('#/timeline?from=2026-03-22T02:00:00Z')?.issue).toContain('両方')
    expect(parseTimelineHash('#/timeline?to=2026-03-22T02:00:00Z')?.issue).toContain('両方')
    expect(parseTimelineHash('#/timeline?from=bad&to=worse')?.issue).toContain('解釈できません')
    expect(parseTimelineHash('#/timeline?range=2h')?.issue).toContain('range')
    expect(parseTimelineHash('#/timeline?range=1h&anchor=bad')?.issue).toContain('anchor')
    expect(parseTimelineHash('#/timeline?range=1h&vcenter_id=not-a-uuid')?.issue).toContain('UUID')
    expect(parseTimelineHash('#/timeline?range=1h&vcenter_id=not-a-uuid')?.conditions.vcenterId).toBe('')
  })

  it.each(['', '&vcenter_id=not-a-uuid'])('vCenter が無いか読めない URL では moid を捨てて理由を返す（%s）', (vcenter) => {
    const parsed = parseTimelineHash(`#/timeline?range=1h&entity=esx&entity_moid=host-10${vcenter}`)
    expect(parsed?.issue).toContain('entity_moid')
    expect(parsed?.conditions).toMatchObject({ entity: 'esx', entityMoid: null, vcenterId: '' })
  })

  it('範囲外の min_score と不明な sources は既定に落とす（issue にはしない）', () => {
    const parsed = parseTimelineHash('#/timeline?range=1h&min_score=500&sources=nope')
    expect(parsed).toEqual({ conditions: DEFAULT_TIMELINE_CONDITIONS, issue: null })
  })

  it('Z の無い from / to / anchor はローカル時刻ではなく UTC として読む', () => {
    const parsed = parseTimelineHash(
      '#/timeline?from=2026-03-22T00:00:00&to=2026-03-22T01:30&anchor=2026-03-22T00:40:00.5',
    )
    expect(parsed?.issue).toBeNull()
    expect(parsed?.conditions.range).toEqual({
      mode: 'fixed',
      from: '2026-03-22T00:00:00.000Z',
      to: '2026-03-22T01:30:00.000Z',
    })
    expect(parsed?.conditions.anchor).toBe('2026-03-22T00:40:00.500Z')
  })

  it('replaceTimelineHash は履歴を増やさずハッシュだけを書き換える', () => {
    window.history.replaceState(null, '', '/?x=1#/timeline')
    const before = window.history.length
    replaceTimelineHash(FIXED)
    expect(window.history.length).toBe(before)
    expect(window.location.search).toBe('?x=1')
    expect(readTimelineHash()).toEqual({ conditions: FIXED, issue: null })
  })

  it('イベント・ログ用の読み書きには影響しない', () => {
    const hash = correlationHash('events', { vcenterId: 'vc-1', from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T00:10:00.000Z' })
    window.history.replaceState(null, '', hash)
    expect(readTimelineHash()).toBeNull()
    expect(readCorrelationRange('events')).not.toBeNull()
    window.history.replaceState(null, '', buildTimelineHash(FIXED))
    expect(readCorrelationRange('events')).toBeNull()
  })
})

describe('timelineHash の種別としきい値', () => {
  const ALL = ['event', 'alert', 'metric', 'log']

  it('既定は 4 種類すべてで、URL には出さない', () => {
    expect(DEFAULT_TIMELINE_CONDITIONS.sources).toEqual(ALL)
    expect(buildTimelineHash(DEFAULT_TIMELINE_CONDITIONS)).toBe('#/timeline?range=1h')
    // 4 種類を明示した URL も既定として読める
    expect(parseTimelineHash(`#/timeline?range=1h&sources=${ALL.join(',')}`)?.conditions.sources).toEqual(ALL)
  })

  it('メトリクスとログを含む種別の組を往復できる（順序は正規化される）', () => {
    const conditions = { ...DEFAULT_TIMELINE_CONDITIONS, sources: ['metric', 'log'] as const }
    const hash = buildTimelineHash(conditions)
    expect(hash).toBe('#/timeline?range=1h&sources=metric%2Clog')
    expect(parseTimelineHash(hash)?.conditions.sources).toEqual(['metric', 'log'])
    expect(parseTimelineHash('#/timeline?range=1h&sources=log,event')?.conditions.sources).toEqual(['event', 'log'])
    expect(parseTimelineHash('#/timeline?range=1h&sources=event,alert,metric')?.conditions.sources).toEqual([
      'event',
      'alert',
      'metric',
    ])
  })

  it('しきい値の既定（CPU 80・メモリ 85）は URL に出さず、既定でない値だけ出す', () => {
    expect(DEFAULT_TIMELINE_CONDITIONS.cpuThresholdPct).toBe(80)
    expect(DEFAULT_TIMELINE_CONDITIONS.memoryThresholdPct).toBe(85)
    const cpu = buildTimelineHash({ ...DEFAULT_TIMELINE_CONDITIONS, cpuThresholdPct: 90 })
    expect(cpu).toBe('#/timeline?range=1h&cpu_threshold=90')
    expect(buildTimelineHash({ ...DEFAULT_TIMELINE_CONDITIONS, memoryThresholdPct: 70.5 })).toBe(
      '#/timeline?range=1h&memory_threshold=70.5',
    )
    const parsed = parseTimelineHash('#/timeline?range=1h&cpu_threshold=90&memory_threshold=70.5')
    expect(parsed?.conditions.cpuThresholdPct).toBe(90)
    expect(parsed?.conditions.memoryThresholdPct).toBe(70.5)
    expect(parsed?.issue).toBeNull()
  })

  it('0 や 100 は有効なしきい値として読める', () => {
    const parsed = parseTimelineHash('#/timeline?range=1h&cpu_threshold=0&memory_threshold=100')
    expect(parsed?.conditions.cpuThresholdPct).toBe(0)
    expect(parsed?.conditions.memoryThresholdPct).toBe(100)
    expect(parsed?.issue).toBeNull()
  })

  it.each(['abc', '101', '-1', '', 'Infinity'])('しきい値 %s は黙って既定にせず、理由（issue）を返す', (raw) => {
    const parsed = parseTimelineHash(`#/timeline?range=1h&cpu_threshold=${raw}`)
    expect(parsed?.issue).toContain('cpu_threshold')
    expect(parsed?.conditions.cpuThresholdPct).toBe(80)
    expect(parseTimelineHash(`#/timeline?range=1h&memory_threshold=${raw}`)?.issue).toContain('memory_threshold')
  })
})

describe('timelineEntryHash', () => {
  const VC = '11111111-1111-4111-8111-111111111111'

  it('起点の前後 30 分を既定の幅にして、anchor・vcenter_id・entity を持つ', () => {
    const hash = timelineEntryHash({ at: '2026-03-22T01:00:00Z', vcenterId: VC, entity: 'esx 01' })
    expect(hash).not.toBeNull()
    const parsed = parseTimelineHash(hash!)!
    expect(parsed.issue).toBeNull()
    expect(parsed.conditions.range).toEqual({
      mode: 'fixed',
      from: '2026-03-22T00:30:00.000Z',
      to: '2026-03-22T01:30:00.000Z',
    })
    expect(parsed.conditions.anchor).toBe('2026-03-22T01:00:00.000Z')
    expect(parsed.conditions.vcenterId).toBe(VC)
    expect(parsed.conditions.entity).toBe('esx 01')
  })

  it('幅を指定でき、vCenter と対象が無ければ項目を出さない', () => {
    const hash = timelineEntryHash({ at: '2026-03-22T01:00:00Z', halfWidthMs: 600_000 })!
    expect(hash).toContain('from=2026-03-22T00%3A50%3A00.000Z')
    expect(hash).toContain('to=2026-03-22T01%3A10%3A00.000Z')
    expect(hash).not.toContain('vcenter_id')
    expect(hash).not.toContain('entity')
    expect(timelineEntryHash({ at: '2026-03-22T01:00:00Z', vcenterId: '', entity: null, entityMoid: 'host-10' })).not.toContain('entity')
  })

  it('Z の無い時刻は UTC として読む（ローカル時刻にしない）', () => {
    const hash = timelineEntryHash({ at: '2026-03-22T01:00:00' })!
    expect(parseTimelineHash(hash)!.conditions.anchor).toBe('2026-03-22T01:00:00.000Z')
  })

  it('読めない時刻・空は null', () => {
    expect(timelineEntryHash({ at: 'not a date' })).toBeNull()
    expect(timelineEntryHash({ at: '' })).toBeNull()
    expect(timelineEntryHash({ at: null })).toBeNull()
    expect(timelineEntryHash({ at: undefined })).toBeNull()
  })

  it.each(['a&b=c', 'host#1', 'a+b', '100%', 'ホスト 01 / テスト', 'x?y=1&z#2+%41'])(
    '対象名「%s」を壊さずに URL へ入れ、読み戻せる',
    (entity) => {
      const hash = timelineEntryHash({ at: '2026-03-22T01:00:00Z', vcenterId: VC, entity })!
      // ハッシュの区切りになる文字が生のまま混ざらない（# は先頭の 1 つだけ）
      expect(hash.indexOf('#')).toBe(0)
      expect(hash.lastIndexOf('#')).toBe(0)
      const parsed = parseTimelineHash(hash)!
      expect(parsed.issue).toBeNull()
      expect(parsed.conditions.entity).toBe(entity.trim())
      expect(parsed.conditions.vcenterId).toBe(VC)
      expect(parsed.conditions.anchor).toBe('2026-03-22T01:00:00.000Z')
    },
  )

  it('未来になる to もそのまま作る', () => {
    const future = new Date(Date.now() + 10 * 60_000).toISOString()
    const parsed = parseTimelineHash(timelineEntryHash({ at: future })!)!
    expect(parsed.issue).toBeNull()
    expect(parsed.conditions.range.mode).toBe('fixed')
  })
})
