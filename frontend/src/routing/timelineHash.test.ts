/** @vitest-environment happy-dom */
import { describe, expect, it } from 'vitest'

import { correlationHash, readCorrelationRange } from './correlationRange'
import {
  buildTimelineHash,
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
  minScore: 40,
  sources: ['alert'],
}

describe('timelineHash', () => {
  it('固定の期間と全条件を往復できる', () => {
    const hash = buildTimelineHash(FIXED)
    expect(hash).toContain('from=2026-03-22T00%3A00%3A00.000Z')
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
