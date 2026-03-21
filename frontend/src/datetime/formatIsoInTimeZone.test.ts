import { describe, expect, it } from 'vitest'
import {
  extractTickAxisValue,
  formatChartAxisTick,
  formatIsoInTimeZone,
  parseApiUtcInstantMs,
} from './formatIsoInTimeZone'

describe('parseApiUtcInstantMs', () => {
  it('treats naive ISO datetime as UTC (matches Z suffix)', () => {
    const naive = '2025-06-15T03:00:05'
    const withZ = '2025-06-15T03:00:05.000Z'
    expect(parseApiUtcInstantMs(naive)).toBe(new Date(withZ).getTime())
  })

  it('passes through explicit Z', () => {
    const s = '2025-06-15T03:00:05.000Z'
    expect(parseApiUtcInstantMs(s)).toBe(new Date(s).getTime())
  })
})

describe('formatIsoInTimeZone', () => {
  it('formats UTC instant in Asia/Tokyo', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:00.000Z', 'Asia/Tokyo')
    expect(s).toMatch(/2025/)
    expect(s).toMatch(/12:00/)
  })

  it('naive ISO without Z matches same wall time as explicit UTC for display', () => {
    const naive = formatIsoInTimeZone('2025-06-15T03:00:05', 'Asia/Tokyo', { omitSeconds: true })
    const z = formatIsoInTimeZone('2025-06-15T03:00:05.000Z', 'Asia/Tokyo', { omitSeconds: true })
    expect(naive).toBe(z)
  })

  it('omitSeconds avoids HH:mm:ss on the time axis style output', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:05.000Z', 'Asia/Tokyo', {
      omitSeconds: true,
    })
    expect(s).not.toMatch(/\d{1,2}:\d{2}:\d{2}/)
  })

  it('returns em dash for invalid date string', () => {
    expect(formatIsoInTimeZone('not-a-date', 'UTC')).toBe('—')
  })
})

describe('extractTickAxisValue', () => {
  it('returns inner value when payload is a Recharts tick object', () => {
    expect(extractTickAxisValue({ value: 42, coordinate: 0 })).toBe(42)
  })

  it('returns payload when it is already the raw value', () => {
    expect(extractTickAxisValue(42)).toBe(42)
  })
})

describe('formatChartAxisTick', () => {
  it('formats Date with IANA zone (not browser default string)', () => {
    const d = new Date('2025-06-15T03:00:00.000Z')
    const s = formatChartAxisTick(d, 'Asia/Tokyo')
    expect(s).toMatch(/2025/)
    expect(s).toMatch(/12:00/)
  })

  it('formats epoch ms', () => {
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'UTC')
    expect(s).toMatch(/2025/)
  })
})
