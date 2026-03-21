import { describe, expect, it } from 'vitest'
import {
  combineDateAndOptionalTime,
  presetRelativeRangeWallParts,
  splitZonedLocalDateTimeInput,
  zonedRangePartsToCombinedInputs,
} from './zonedRangeParts'

describe('combineDateAndOptionalTime', () => {
  it('returns empty when date is empty', () => {
    expect(combineDateAndOptionalTime('', '12:00', 'start')).toBe('')
  })

  it('uses 00:00 for start when time empty', () => {
    expect(combineDateAndOptionalTime('2025-06-15', '', 'start')).toBe('2025-06-15T00:00')
  })

  it('uses 23:59 for end when time empty', () => {
    expect(combineDateAndOptionalTime('2025-06-15', '', 'end')).toBe('2025-06-15T23:59')
  })

  it('uses explicit time when set', () => {
    expect(combineDateAndOptionalTime('2025-06-15', '14:30', 'start')).toBe('2025-06-15T14:30')
  })
})

describe('zonedRangePartsToCombinedInputs', () => {
  it('merges four fields', () => {
    const r = zonedRangePartsToCombinedInputs({
      fromDate: '2025-01-01',
      fromTime: '10:00',
      toDate: '2025-01-02',
      toTime: '',
    })
    expect(r.rangeFromInput).toBe('2025-01-01T10:00')
    expect(r.rangeToInput).toBe('2025-01-02T23:59')
  })
})

describe('splitZonedLocalDateTimeInput', () => {
  it('splits combined string', () => {
    expect(splitZonedLocalDateTimeInput('2025-06-15T12:30')).toEqual({
      date: '2025-06-15',
      time: '12:30',
    })
  })
})

describe('presetRelativeRangeWallParts', () => {
  it('returns non-empty parts for Tokyo', () => {
    const p = presetRelativeRangeWallParts(3600000, 'Asia/Tokyo')
    expect(p.fromDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(p.toDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(p.fromTime).toMatch(/^\d{2}:\d{2}$/)
    expect(p.toTime).toMatch(/^\d{2}:\d{2}$/)
  })
})
