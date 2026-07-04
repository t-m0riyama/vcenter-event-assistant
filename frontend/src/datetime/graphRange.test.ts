import { describe, expect, it } from 'vitest'
import {
  resolveEventApiRange,
  resolveMetricsGraphRange,
  summarizeGraphRangePreview,
} from './graphRange'

describe('resolveEventApiRange', () => {
  it('returns ok with no bounds when both empty', () => {
    expect(resolveEventApiRange('', '', 'UTC')).toEqual({ ok: true })
  })

  it('allows from-only', () => {
    const r = resolveEventApiRange('2025-06-15T10:00', '', 'UTC')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.from).toBe('2025-06-15T10:00:00.000Z')
      expect(r.to).toBeUndefined()
    }
  })

  it('allows to-only', () => {
    const r = resolveEventApiRange('', '2025-06-15T23:59', 'UTC')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.to).toBe('2025-06-15T23:59:59.000Z')
    }
  })

  it('rejects from >= to', () => {
    const r = resolveEventApiRange('2025-06-16T12:00', '2025-06-15T12:00', 'UTC')
    expect(r).toEqual({ ok: false, message: '開始は終了より前の時刻にしてください。' })
  })

  it('extends T23:59 to end of wall minute for to', () => {
    const r = resolveEventApiRange('2025-06-15T00:00', '2025-06-15T23:59', 'UTC')
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.to).toBe('2025-06-15T23:59:59.000Z')
    }
  })
})

describe('resolveMetricsGraphRange', () => {
  it('returns none when both empty', () => {
    expect(resolveMetricsGraphRange('', '', 'UTC')).toEqual({ mode: 'none' })
  })

  it('rejects one-sided input', () => {
    const r = resolveMetricsGraphRange('2025-06-15T00:00', '', 'UTC')
    expect(r.mode).toBe('invalid')
    if (r.mode === 'invalid') {
      expect(r.message).toContain('片方だけでは指定できません')
    }
  })

  it('returns range when both valid', () => {
    const r = resolveMetricsGraphRange('2025-06-15T00:00', '2025-06-16T00:00', 'UTC')
    expect(r).toEqual({
      mode: 'range',
      from: '2025-06-15T00:00:00.000Z',
      to: '2025-06-16T00:00:00.000Z',
    })
  })
})

describe('summarizeGraphRangePreview', () => {
  it('returns 指定なし when empty', () => {
    expect(
      summarizeGraphRangePreview({
        fromDate: '',
        fromTime: '',
        toDate: '',
        toTime: '',
      }),
    ).toBe('指定なし')
  })

  it('returns 入力中 when partial', () => {
    expect(
      summarizeGraphRangePreview({
        fromDate: '2025-06-01',
        fromTime: '10:00',
        toDate: '',
        toTime: '',
      }),
    ).toBe('入力中')
  })

  it('returns date span when complete', () => {
    expect(
      summarizeGraphRangePreview({
        fromDate: '2025-06-01',
        fromTime: '10:00',
        toDate: '2025-06-02',
        toTime: '11:00',
      }),
    ).toBe('2025-06-01 ～ 2025-06-02')
  })
})
