import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getWallClockInZone,
  isValidUtcRangeOrder,
  parseZonedLocalDateTimeInput,
  utcIsoToZonedLocalDateTimeInput,
  zonedCalendarDateMidnightUtcMs,
  zonedLocalDateTimeToUtcIso,
} from './zonedLocalDateTime'

describe('parseZonedLocalDateTimeInput', () => {
  it('accepts YYYY-MM-DDTHH:mm', () => {
    expect(parseZonedLocalDateTimeInput('2025-06-15T12:30')).toEqual({
      year: 2025,
      month: 6,
      day: 15,
      hour: 12,
      minute: 30,
    })
  })

  it('rejects invalid shapes', () => {
    expect(parseZonedLocalDateTimeInput('2025-6-15T12:30')).toBeNull()
    expect(parseZonedLocalDateTimeInput('')).toBeNull()
    expect(parseZonedLocalDateTimeInput('2025-06-15')).toBeNull()
  })
})

describe('zonedLocalDateTimeToUtcIso', () => {
  it('maps Asia/Tokyo wall time to UTC (JST = UTC+9)', () => {
    const iso = zonedLocalDateTimeToUtcIso('2025-06-15T12:00', 'Asia/Tokyo')
    expect(iso).toBe('2025-06-15T03:00:00.000Z')
  })

  it('round-trips with utcIsoToZonedLocalDateTimeInput (minute precision)', () => {
    const utc = '2025-03-10T08:15:00.000Z'
    const local = utcIsoToZonedLocalDateTimeInput(utc, 'Europe/Berlin')
    const back = zonedLocalDateTimeToUtcIso(local, 'Europe/Berlin')
    expect(back).toBeTruthy()
    expect(back!.slice(0, 19)).toBe('2025-03-10T08:15:00')
  })

  it('returns null for invalid time zone', () => {
    expect(zonedLocalDateTimeToUtcIso('2025-06-15T12:00', 'Not/AZone')).toBeNull()
  })
})

describe('zonedLocalDateTimeToUtcIso midnight', () => {
  it('resolves Asia/Tokyo local midnight (not only noon)', () => {
    expect(zonedLocalDateTimeToUtcIso('2025-06-15T00:00', 'Asia/Tokyo')).toBe(
      '2025-06-14T15:00:00.000Z',
    )
    expect(zonedLocalDateTimeToUtcIso('2026-06-15T00:00', 'Asia/Tokyo')).toBe(
      '2026-06-14T15:00:00.000Z',
    )
  })
})

describe('zonedCalendarDateMidnightUtcMs', () => {
  it('returns UTC ms for local midnight (Asia/Tokyo)', () => {
    const ms = zonedCalendarDateMidnightUtcMs(2026, 6, 15, 'Asia/Tokyo')
    expect(ms).not.toBeNull()
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    expect(ms!).toBeGreaterThan(nowMs)
  })
})

describe('isValidUtcRangeOrder', () => {
  it('is true when from is strictly before to', () => {
    expect(
      isValidUtcRangeOrder('2025-01-01T00:00:00.000Z', '2025-01-02T00:00:00.000Z'),
    ).toBe(true)
  })

  it('is false when equal or reversed', () => {
    expect(isValidUtcRangeOrder('2025-01-01T00:00:00.000Z', '2025-01-01T00:00:00.000Z')).toBe(
      false,
    )
    expect(isValidUtcRangeOrder('2025-01-02T00:00:00.000Z', '2025-01-01T00:00:00.000Z')).toBe(
      false,
    )
  })
})

describe('getWallClockInZone', () => {
  it('returns Tokyo wall time for a UTC instant', () => {
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const w = getWallClockInZone(ms, 'Asia/Tokyo')
    expect(w.year).toBe(2025)
    expect(w.month).toBe(6)
    expect(w.day).toBe(15)
    expect(w.hour).toBe(12)
    expect(w.minute).toBe(0)
  })

  it('JST 0:00 ちょうどは当日の 0:00 として解釈する（前日 15:00 UTC）', () => {
    const ms = new Date('2025-06-14T15:00:00.000Z').getTime()
    const w = getWallClockInZone(ms, 'Asia/Tokyo')
    expect(w.year).toBe(2025)
    expect(w.month).toBe(6)
    expect(w.day).toBe(15)
    expect(w.hour).toBe(0)
    expect(w.minute).toBe(0)
  })

  it('年跨ぎ（UTC の大晦日 15:00 = JST 元日 0:00）でも日付が正しい', () => {
    const ms = new Date('2024-12-31T15:00:00.000Z').getTime()
    const w = getWallClockInZone(ms, 'Asia/Tokyo')
    expect(w.year).toBe(2025)
    expect(w.month).toBe(1)
    expect(w.day).toBe(1)
    expect(w.hour).toBe(0)
    expect(w.minute).toBe(0)
  })
})

const wall = (iso: string, tz: string) => {
  const w = getWallClockInZone(new Date(iso).getTime(), tz)
  return [w.year, w.month, w.day, w.hour, w.minute]
}

describe('getWallClockInZone 0 時台', () => {
  it.each([
    ['2026-03-22T15:00:00Z', [2026, 3, 23, 0, 0]],
    ['2026-03-22T15:01:00Z', [2026, 3, 23, 0, 1]],
    ['2026-03-22T15:30:00Z', [2026, 3, 23, 0, 30]],
    ['2026-03-22T15:59:00Z', [2026, 3, 23, 0, 59]],
    ['2026-03-22T16:00:00Z', [2026, 3, 23, 1, 0]],
    ['2026-03-23T14:59:00Z', [2026, 3, 23, 23, 59]],
  ])('Asia/Tokyo %s', (iso, expected) => {
    expect(wall(iso, 'Asia/Tokyo')).toEqual(expected)
  })

  it('UTC の 0 時台', () => {
    expect(wall('2026-03-23T00:00:00Z', 'UTC')).toEqual([2026, 3, 23, 0, 0])
    expect(wall('2026-03-23T00:30:00Z', 'UTC')).toEqual([2026, 3, 23, 0, 30])
    expect(wall('2026-03-23T00:59:00Z', 'UTC')).toEqual([2026, 3, 23, 0, 59])
  })

  it('America/New_York（負のオフセット）の 0 時台', () => {
    // EDT = UTC-4
    expect(wall('2026-06-15T04:00:00Z', 'America/New_York')).toEqual([2026, 6, 15, 0, 0])
    expect(wall('2026-06-15T04:30:00Z', 'America/New_York')).toEqual([2026, 6, 15, 0, 30])
    expect(wall('2026-06-15T04:59:00Z', 'America/New_York')).toEqual([2026, 6, 15, 0, 59])
  })

  it('夏時間の切り替え日（2026-03-08 進む日 / 2026-11-01 戻る日）でも 0 時台の日付が正しい', () => {
    // 03-08: 0:30 は EST (UTC-5)
    expect(wall('2026-03-08T05:30:00Z', 'America/New_York')).toEqual([2026, 3, 8, 0, 30])
    // 11-01: 0:30 は EDT (UTC-4)
    expect(wall('2026-11-01T04:30:00Z', 'America/New_York')).toEqual([2026, 11, 1, 0, 30])
    // 戻る日の 1:30 は 2 回ある
    expect(wall('2026-11-01T05:30:00Z', 'America/New_York')).toEqual([2026, 11, 1, 1, 30])
    expect(wall('2026-11-01T06:30:00Z', 'America/New_York')).toEqual([2026, 11, 1, 1, 30])
  })
})

describe('0 時台の往復', () => {
  const utcs = [
    '2026-03-22T15:00:00.000Z',
    '2026-03-22T15:01:00.000Z',
    '2026-03-22T15:30:00.000Z',
    '2026-03-23T00:30:00.000Z',
    '2026-06-15T04:30:00.000Z',
    '2026-11-01T04:30:00.000Z',
  ]
  it.each(['Asia/Tokyo', 'UTC', 'America/New_York'])('%s', (tz) => {
    for (const utc of utcs) {
      const local = utcIsoToZonedLocalDateTimeInput(utc, tz)
      expect(local).not.toBe('')
      expect(zonedLocalDateTimeToUtcIso(local, tz)).toBe(utc)
    }
  })

  it('Asia/Tokyo 00:30 は前日 15:30 UTC', () => {
    expect(zonedLocalDateTimeToUtcIso('2026-03-23T00:30', 'Asia/Tokyo')).toBe(
      '2026-03-22T15:30:00.000Z',
    )
    expect(utcIsoToZonedLocalDateTimeInput('2026-03-22T15:30:00.000Z', 'Asia/Tokyo')).toBe(
      '2026-03-23T00:30',
    )
  })

  it('夏時間: 存在しない 2:30 は null、0:30 は解決できる', () => {
    expect(zonedLocalDateTimeToUtcIso('2026-03-08T02:30', 'America/New_York')).toBeNull()
    expect(zonedLocalDateTimeToUtcIso('2026-03-08T00:30', 'America/New_York')).toBe(
      '2026-03-08T05:30:00.000Z',
    )
    expect(zonedLocalDateTimeToUtcIso('2026-11-01T00:30', 'America/New_York')).toBe(
      '2026-11-01T04:30:00.000Z',
    )
  })
})

describe('Intl が 0 時を 24 と返す実行環境', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hour 24 は同じ日の 0 時として扱い、日付を進めない', () => {
    const Real = Intl.DateTimeFormat
    class H24 extends Real {
      override formatToParts(date?: Date | number): Intl.DateTimeFormatPart[] {
        return super.formatToParts(date).map((p) =>
          p.type === 'hour' && p.value === '00' ? { ...p, value: '24' } : p,
        )
      }
    }
    vi.stubGlobal('Intl', { ...Intl, DateTimeFormat: H24 })
    const w = getWallClockInZone(new Date('2026-03-22T15:30:00Z').getTime(), 'Asia/Tokyo')
    expect([w.year, w.month, w.day, w.hour, w.minute]).toEqual([2026, 3, 23, 0, 30])
  })
})
