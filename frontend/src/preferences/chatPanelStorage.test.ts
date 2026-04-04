import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  CHAT_PANEL_STORAGE_KEY,
  clearChatPanelSnapshot,
  DEFAULT_CHAT_MAX_STORED_MESSAGES,
  readChatPanelSnapshot,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from './chatPanelStorage'

/** テスト用の最小スナップショット（Zod 通過用） */
function minimalSnapshot(overrides?: Partial<Parameters<typeof writeChatPanelSnapshot>[0]>) {
  return {
    messages: [{ role: 'user' as const, content: 'hello' }],
    rangeParts: {
      fromDate: '2026-01-01',
      fromTime: '00:00',
      toDate: '2026-01-02',
      toTime: '23:59',
    },
    vcenterId: '',
    includePeriodMetricsCpu: false,
    includePeriodMetricsMemory: false,
    includePeriodMetricsDiskIo: false,
    includePeriodMetricsNetworkIo: false,
    draft: '',
    ...overrides,
  }
}

describe('trimChatMessagesToMax', () => {
  it('件数が上限以下ならそのまま返す', () => {
    const m = [
      { role: 'user' as const, content: 'a' },
      { role: 'assistant' as const, content: 'b' },
    ]
    expect(trimChatMessagesToMax(m, 10)).toEqual(m)
  })

  it('201 件なら末尾 200 件を残す（FIFO）', () => {
    const many = Array.from({ length: 201 }, (_, i) => ({
      role: (i % 2 === 0 ? 'user' : 'assistant') as 'user' | 'assistant',
      content: String(i),
    }))
    const out = trimChatMessagesToMax(many, DEFAULT_CHAT_MAX_STORED_MESSAGES)
    expect(out).toHaveLength(200)
    expect(out[0]?.content).toBe('1')
    expect(out[199]?.content).toBe('200')
  })
})

describe('readChatPanelSnapshot / writeChatPanelSnapshot / clearChatPanelSnapshot', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_PANEL_STORAGE_KEY)
  })

  it('未設定なら null', () => {
    expect(readChatPanelSnapshot()).toBeNull()
  })

  it('write 後に read で同一内容が得られる', () => {
    const snap = minimalSnapshot({ draft: '下書き', vcenterId: 'vc-1' })
    writeChatPanelSnapshot(snap)
    expect(readChatPanelSnapshot()).toEqual(snap)
  })

  it('不正 JSON なら null にしキーを削除する', () => {
    localStorage.setItem(CHAT_PANEL_STORAGE_KEY, '{broken')
    expect(readChatPanelSnapshot()).toBeNull()
    expect(localStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('Zod に通らないオブジェクトなら null にしキーを削除する', () => {
    localStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ foo: 1 }))
    expect(readChatPanelSnapshot()).toBeNull()
    expect(localStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('write は messages を最大件数にトリムしてから保存する', () => {
    const many = Array.from({ length: 201 }, (_, i) => ({
      role: 'user' as const,
      content: `m${i}`,
    }))
    writeChatPanelSnapshot(minimalSnapshot({ messages: many }))
    const got = readChatPanelSnapshot()
    expect(got?.messages).toHaveLength(200)
    expect(got?.messages[0]?.content).toBe('m1')
  })

  it('clearChatPanelSnapshot でキーが消える', () => {
    writeChatPanelSnapshot(minimalSnapshot())
    clearChatPanelSnapshot()
    expect(localStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('localStorage が無い環境では read は null・write/clear は no-op', () => {
    vi.stubGlobal('localStorage', undefined)
    expect(readChatPanelSnapshot()).toBeNull()
    expect(() => writeChatPanelSnapshot(minimalSnapshot())).not.toThrow()
    expect(() => clearChatPanelSnapshot()).not.toThrow()
    vi.unstubAllGlobals()
  })
})
