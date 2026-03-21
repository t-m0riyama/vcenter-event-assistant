import { describe, expect, it } from 'vitest'
import { formatIsoInTimeZone } from './formatIsoInTimeZone'

describe('formatIsoInTimeZone', () => {
  it('formats UTC instant in Asia/Tokyo', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:00.000Z', 'Asia/Tokyo')
    expect(s).toMatch(/2025/)
    expect(s).toMatch(/12:00/)
  })

  it('returns em dash for invalid date string', () => {
    expect(formatIsoInTimeZone('not-a-date', 'UTC')).toBe('—')
  })
})
