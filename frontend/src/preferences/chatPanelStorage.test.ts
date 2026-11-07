import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  activateChatScope,
  CHAT_PANEL_STORAGE_KEY,
  type ChatStorageScope,
  clearChatPanelSnapshot,
  DEFAULT_CHAT_MAX_STORED_MESSAGES,
  readChatPanelSnapshot,
  releaseChatScope,
  trimChatMessagesToMax,
  writeChatPanelSnapshot,
} from './chatPanelStorage'

/** テスト用の最小スナップショット（Zod 通過用） */
function minimalSnapshot(overrides?: Partial<Parameters<typeof writeChatPanelSnapshot>[1]>) {
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
  const owner = 'session:test'
  let scope: ChatStorageScope | null
  beforeEach(() => {
    scope = activateChatScope(owner)
  })
  afterEach(() => {
    activateChatScope(null)
  })

  it('「直近 N」の長さを保存して読み戻す。前の版の保存データ（長さなし）も読める', () => {
    writeChatPanelSnapshot(scope, minimalSnapshot({ rollingDurationMs: 7 * 86400000 }), 200)
    expect(readChatPanelSnapshot(scope, 200)?.rollingDurationMs).toBe(7 * 86400000)
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ ...minimalSnapshot(), owner }))
    const legacy = readChatPanelSnapshot(scope, 200)
    expect(legacy).not.toBeNull()
    expect(legacy?.rollingDurationMs).toBeUndefined()
  })

  it('未設定なら null', () => {
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
  })

  it('write 後に read で同一内容が得られる', () => {
    const snap = minimalSnapshot({ draft: '下書き', vcenterId: 'vc-1' })
    expect(writeChatPanelSnapshot(scope, snap, 200)).toBe('saved')
    expect(readChatPanelSnapshot(scope, 200)).toEqual(snap)
    // 共有端末向け: chat panel 状態は sessionStorage のみ（localStorage には書かない）
    expect(localStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('includeResearch を含む旧スナップショットも読める（後方互換・値は無視）', () => {
    const legacy = { ...minimalSnapshot(), includeResearch: false }
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ ...legacy, owner }))
    const got = readChatPanelSnapshot(scope, 200)
    expect(got).not.toBeNull()
    expect(got).not.toHaveProperty('includeResearch')
  })

  it('不正 JSON なら null にしキーを削除する', () => {
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, '{broken')
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
    expect(sessionStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('Zod に通らないオブジェクトなら null にしキーを削除する', () => {
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ foo: 1 }))
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
    expect(sessionStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('write は messages を最大件数にトリムしてから保存する', () => {
    const many = Array.from({ length: 201 }, (_, i) => ({
      role: 'user' as const,
      content: `m${i}`,
    }))
    expect(writeChatPanelSnapshot(scope, minimalSnapshot({ messages: many }), 200)).toBe('saved')
    const got = readChatPanelSnapshot(scope, 200)
    expect(got?.messages).toHaveLength(200)
    expect(got?.messages[0]?.content).toBe('m1')
  })

  it('maxStoredMessages が 0 のとき read の messages は空', () => {
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ ...minimalSnapshot(), owner }))
    expect(readChatPanelSnapshot(scope, 0)?.messages).toEqual([])
  })

  it('read は messages を最大件数にトリムする（ストレージに 200 件超があっても）', () => {
    const many = Array.from({ length: 250 }, (_, i) => ({
      role: 'user' as const,
      content: `m${i}`,
    }))
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify({ ...minimalSnapshot({ messages: many }), owner }))
    const got = readChatPanelSnapshot(scope, 200)
    expect(got?.messages).toHaveLength(200)
    expect(got?.messages[0]?.content).toBe('m50')
  })

  it('setItem が失敗したとき write は失敗を返す', () => {
    const spy = vi.spyOn(sessionStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('quota', 'QuotaExceededError')
    })
    expect(writeChatPanelSnapshot(scope, minimalSnapshot(), 200)).toBe('failed')
    spy.mockRestore()
  })

  it('clearChatPanelSnapshot でキーが消える', () => {
    expect(writeChatPanelSnapshot(scope, minimalSnapshot(), 200)).toBe('saved')
    clearChatPanelSnapshot(scope)
    expect(sessionStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('sessionStorage が無い環境では read は null・write は失敗・clear は no-op', () => {
    vi.stubGlobal('sessionStorage', undefined)
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
    expect(writeChatPanelSnapshot(scope, minimalSnapshot(), 200)).toBe('failed')
    expect(() => clearChatPanelSnapshot(scope)).not.toThrow()
    vi.unstubAllGlobals()
  })

  it('所有者なしの旧形式と異なる所有者の保存を破棄する', () => {
    sessionStorage.setItem('vea.chat_panel.v1', JSON.stringify(minimalSnapshot()))
    localStorage.setItem('vea.chat_panel.v1', JSON.stringify(minimalSnapshot()))
    sessionStorage.setItem(CHAT_PANEL_STORAGE_KEY, JSON.stringify(minimalSnapshot()))
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
    writeChatPanelSnapshot(scope, minimalSnapshot({ draft: 'A' }), 200)
    const other = activateChatScope('session:other')
    expect(readChatPanelSnapshot(other, 200)).toBeNull()
    expect(sessionStorage.getItem('vea.chat_panel.v1')).toBeNull()
    expect(localStorage.getItem('vea.chat_panel.v1')).toBeNull()
    expect(sessionStorage.getItem(CHAT_PANEL_STORAGE_KEY)).toBeNull()
  })

  it('同じ所有者に戻っても旧スコープからの保存と消去を拒否する', () => {
    activateChatScope('session:other')
    const current = activateChatScope(owner)
    expect(current).not.toBe(scope)
    writeChatPanelSnapshot(current, minimalSnapshot({ draft: 'current' }), 200)
    expect(writeChatPanelSnapshot(scope, minimalSnapshot({ draft: 'old' }), 200)).toBe('skipped')
    clearChatPanelSnapshot(scope)
    expect(readChatPanelSnapshot(current, 200)?.draft).toBe('current')
  })

  it('画面の再作成では同じセッションの保存を維持し、旧参照を無効にする', () => {
    writeChatPanelSnapshot(scope, minimalSnapshot({ draft: 'saved' }), 200)
    releaseChatScope(scope)
    const reopened = activateChatScope(owner)
    expect(reopened).not.toBe(scope)
    expect(readChatPanelSnapshot(reopened, 200)?.draft).toBe('saved')
    expect(readChatPanelSnapshot(scope, 200)).toBeNull()
  })

  it('削除に失敗しても旧データを復元せず、スコープを切り替えられる', () => {
    writeChatPanelSnapshot(scope, minimalSnapshot({ draft: 'old' }), 200)
    const remove = vi.spyOn(sessionStorage, 'removeItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    try {
      activateChatScope('session:other')
      const current = activateChatScope(owner)
      expect(readChatPanelSnapshot(current, 200)).toBeNull()
      expect(writeChatPanelSnapshot(scope, minimalSnapshot(), 200)).toBe('skipped')
    } finally {
      remove.mockRestore()
    }
  })
})
