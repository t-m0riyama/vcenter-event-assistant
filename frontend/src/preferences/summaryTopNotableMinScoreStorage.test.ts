import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY,
  clampSummaryTopNotableMinScore,
  readStoredSummaryTopNotableMinScore,
  writeStoredSummaryTopNotableMinScore,
} from './summaryTopNotableMinScoreStorage'

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

describe('clampSummaryTopNotableMinScore', () => {
  it('0〜100 に収め、小数は切り捨てる', () => {
    expect(clampSummaryTopNotableMinScore(-5)).toBe(0)
    expect(clampSummaryTopNotableMinScore(101)).toBe(100)
    expect(clampSummaryTopNotableMinScore(42.7)).toBe(42)
  })
})

describe('readStoredSummaryTopNotableMinScore', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('未設定ならデフォルト 1', () => {
    expect(readStoredSummaryTopNotableMinScore()).toBe(1)
  })

  it('有効な整数が保存されていればその値', () => {
    localStorage.setItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY, '40')
    expect(readStoredSummaryTopNotableMinScore()).toBe(40)
  })

  it('数値でない文字列ならデフォルト 1', () => {
    localStorage.setItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY, 'x')
    expect(readStoredSummaryTopNotableMinScore()).toBe(1)
  })

  it('範囲外はクランプ（例: 500 → 100）', () => {
    localStorage.setItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY, '500')
    expect(readStoredSummaryTopNotableMinScore()).toBe(100)
  })
})

describe('writeStoredSummaryTopNotableMinScore', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createMemoryStorage())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('クランプ後の値が保存される', () => {
    writeStoredSummaryTopNotableMinScore(999)
    expect(localStorage.getItem(SUMMARY_TOP_NOTABLE_MIN_SCORE_STORAGE_KEY)).toBe('100')
    expect(readStoredSummaryTopNotableMinScore()).toBe(100)
  })
})
