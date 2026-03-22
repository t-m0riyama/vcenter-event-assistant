import { describe, expect, it } from 'vitest'
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

  it('JST 深夜 0:00 は hour 24 表記でも翌暦日 0:00 として解釈する', () => {
    const ms = new Date('2025-06-14T15:00:00.000Z').getTime()
    const w = getWallClockInZone(ms, 'Asia/Tokyo')
    expect(w.year).toBe(2025)
    expect(w.month).toBe(6)
    expect(w.day).toBe(15)
    expect(w.hour).toBe(0)
    expect(w.minute).toBe(0)
  })

  it('24:00 が年跨ぎでも暦日を繰り上げる', () => {
    const ms = new Date('2024-12-31T15:00:00.000Z').getTime()
    const w = getWallClockInZone(ms, 'Asia/Tokyo')
    expect(w.year).toBe(2025)
    expect(w.month).toBe(1)
    expect(w.day).toBe(1)
    expect(w.hour).toBe(0)
    expect(w.minute).toBe(0)
  })
})
