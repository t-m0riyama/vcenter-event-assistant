import { describe, expect, it } from 'vitest'
import {
  getWallClockInZone,
  isValidUtcRangeOrder,
  parseZonedLocalDateTimeInput,
  utcIsoToZonedLocalDateTimeInput,
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
})
