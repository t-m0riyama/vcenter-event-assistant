import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  AUTO_REFRESH_ENABLED_STORAGE_KEY,
  AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY,
  clampAutoRefreshIntervalMinutes,
  readStoredAutoRefreshEnabled,
  readStoredAutoRefreshIntervalMinutes,
  writeStoredAutoRefreshEnabled,
  writeStoredAutoRefreshIntervalMinutes,
} from './autoRefreshPreferencesStorage'

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

describe('clampAutoRefreshIntervalMinutes', () => {
  it('1〜300 に収め、小数は切り捨てる', () => {
    expect(clampAutoRefreshIntervalMinutes(0)).toBe(1)
    expect(clampAutoRefreshIntervalMinutes(301)).toBe(300)
    expect(clampAutoRefreshIntervalMinutes(42.7)).toBe(42)
  })
})

describe('readStoredAutoRefreshEnabled', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('未設定ならデフォルト true', () => {
    expect(readStoredAutoRefreshEnabled()).toBe(true)
  })

  it('true / 1 が保存されていれば有効', () => {
    localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, 'true')
    expect(readStoredAutoRefreshEnabled()).toBe(true)
    localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, '1')
    expect(readStoredAutoRefreshEnabled()).toBe(true)
  })

  it('false / 0 が保存されていれば無効', () => {
    localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, 'false')
    expect(readStoredAutoRefreshEnabled()).toBe(false)
    localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, '0')
    expect(readStoredAutoRefreshEnabled()).toBe(false)
  })

  it('不正な文字列ならデフォルト true', () => {
    localStorage.setItem(AUTO_REFRESH_ENABLED_STORAGE_KEY, 'maybe')
    expect(readStoredAutoRefreshEnabled()).toBe(true)
  })
})

describe('writeStoredAutoRefreshEnabled', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('文字列として保存される', () => {
    writeStoredAutoRefreshEnabled(false)
    expect(localStorage.getItem(AUTO_REFRESH_ENABLED_STORAGE_KEY)).toBe('false')
    expect(readStoredAutoRefreshEnabled()).toBe(false)
  })
})

describe('readStoredAutoRefreshIntervalMinutes', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('未設定ならデフォルト 5', () => {
    expect(readStoredAutoRefreshIntervalMinutes()).toBe(5)
  })

  it('有効な整数が保存されていればその値（クランプ後）', () => {
    localStorage.setItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY, '60')
    expect(readStoredAutoRefreshIntervalMinutes()).toBe(60)
  })

  it('数値でない文字列ならデフォルト 5', () => {
    localStorage.setItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY, 'x')
    expect(readStoredAutoRefreshIntervalMinutes()).toBe(5)
  })

  it('範囲外はクランプ（例: 0 → 1）', () => {
    localStorage.setItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY, '0')
    expect(readStoredAutoRefreshIntervalMinutes()).toBe(1)
  })
})

describe('writeStoredAutoRefreshIntervalMinutes', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('クランプ後の値が保存される', () => {
    writeStoredAutoRefreshIntervalMinutes(999)
    expect(localStorage.getItem(AUTO_REFRESH_INTERVAL_MINUTES_STORAGE_KEY)).toBe('300')
    expect(readStoredAutoRefreshIntervalMinutes()).toBe(300)
  })
})
