import { describe, expect, it } from 'vitest'
import { getSortedTimeZoneOptions } from './listTimeZones'

describe('getSortedTimeZoneOptions', () => {
  it('returns a non-empty sorted list', () => {
    const list = getSortedTimeZoneOptions()
    expect(list.length).toBeGreaterThan(0)
    const sorted = [...list].sort((a, b) => a.localeCompare(b))
    expect(list).toEqual(sorted)
  })

  it('includes UTC from merged fallback', () => {
    expect(getSortedTimeZoneOptions()).toContain('UTC')
  })
})
