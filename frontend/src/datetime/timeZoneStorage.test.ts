import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DISPLAY_TIME_ZONE_STORAGE_KEY,
  getDefaultBrowserTimeZone,
  isValidIanaTimeZone,
  readStoredTimeZone,
  writeStoredTimeZone,
} from './timeZoneStorage'

function createMemoryStorage(): Storage {
  const map = new Map<string, string>()
  return {
    get length() {
      return map.size
    },
    clear: () => {
      map.clear()
    },
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => {
      map.delete(key)
    },
    setItem: (key: string, value: string) => {
      map.set(key, value)
    },
  } as Storage
}

describe('getDefaultBrowserTimeZone', () => {
  it('matches Intl resolved time zone', () => {
    expect(getDefaultBrowserTimeZone()).toBe(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    )
  })
})

describe('isValidIanaTimeZone', () => {
  it('accepts UTC', () => {
    expect(isValidIanaTimeZone('UTC')).toBe(true)
  })

  it('accepts Asia/Tokyo', () => {
    expect(isValidIanaTimeZone('Asia/Tokyo')).toBe(true)
  })

  it('rejects empty string', () => {
    expect(isValidIanaTimeZone('')).toBe(false)
  })

  it('rejects invalid zone', () => {
    expect(isValidIanaTimeZone('Not/A/Zone')).toBe(false)
  })
})

describe('readStoredTimeZone / writeStoredTimeZone', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns null when key missing', () => {
    expect(readStoredTimeZone()).toBeNull()
  })

  it('round-trips value', () => {
    writeStoredTimeZone('Asia/Tokyo')
    expect(readStoredTimeZone()).toBe('Asia/Tokyo')
    expect(localStorage.getItem(DISPLAY_TIME_ZONE_STORAGE_KEY)).toBe(
      'Asia/Tokyo',
    )
  })
})
