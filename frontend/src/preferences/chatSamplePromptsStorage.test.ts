import { afterEach, describe, expect, it } from 'vitest'

import { INITIAL_CHAT_SAMPLE_PROMPTS } from '../panels/chat/defaultChatSamplePrompts'
import {
  CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
  CHAT_SAMPLE_PROMPTS_STORAGE_KEY,
  readStoredChatSamplePrompts,
  writeStoredChatSamplePrompts,
} from './chatSamplePromptsStorage'

describe('chatSamplePromptsStorage', () => {
  afterEach(() => {
    localStorage.removeItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
    localStorage.removeItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)
  })

  it('新キー未設定かつ旧キーもないとき、INITIAL をシードして新キーに保存し旧キーはない', () => {
    const rows = readStoredChatSamplePrompts()
    expect(rows).toEqual([...INITIAL_CHAT_SAMPLE_PROMPTS])
    const raw = localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)
    expect(raw).toBeTruthy()
    expect(JSON.parse(String(raw))).toEqual([...INITIAL_CHAT_SAMPLE_PROMPTS])
    expect(localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)).toBeNull()
  })

  it('新キーが有効なときそのまま返し、旧キーが残っていれば削除する', () => {
    const only = [{ id: 'x', label: 'L', text: 'T' }]
    localStorage.setItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify(only))
    localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, '[{"id":"legacy","label":"a","text":"b"}]')

    expect(readStoredChatSamplePrompts()).toEqual(only)
    expect(localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)).toBeNull()
  })

  it('新キー未設定で旧キーのみあるとき、INITIAL に旧カスタムを id 重複なしでマージして保存する', () => {
    const legacy = [{ id: 'custom-1', label: 'カスタム', text: '本文' }]
    localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify(legacy))

    const rows = readStoredChatSamplePrompts()
    expect(rows.slice(0, INITIAL_CHAT_SAMPLE_PROMPTS.length)).toEqual([...INITIAL_CHAT_SAMPLE_PROMPTS])
    expect(rows[INITIAL_CHAT_SAMPLE_PROMPTS.length]).toEqual(legacy[0])
    expect(localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)).toBeTruthy()
    expect(localStorage.getItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY)).toBeNull()
  })

  it('旧キーの id が INITIAL と重複する行はマージに含めない', () => {
    const dup = INITIAL_CHAT_SAMPLE_PROMPTS[0]
    localStorage.setItem(CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify([dup]))

    const rows = readStoredChatSamplePrompts()
    expect(rows.filter((r) => r.id === dup.id).length).toBe(1)
  })

  it('新キーが不正 JSON のとき移行し直し、INITIAL＋旧を適用する', () => {
    localStorage.setItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY, '{not json')
    localStorage.setItem(
      CHAT_CUSTOM_SAMPLE_PROMPTS_STORAGE_KEY,
      JSON.stringify([{ id: 'c1', label: 'c', text: 't' }]),
    )

    const rows = readStoredChatSamplePrompts()
    expect(rows.some((r) => r.id === 'c1')).toBe(true)
    expect(localStorage.getItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY)).toBeTruthy()
  })

  it('writeStoredChatSamplePrompts は検証後に新キーへ保存する', () => {
    const rows = [{ id: 'a', label: 'x', text: 'y' }]
    writeStoredChatSamplePrompts(rows)
    expect(readStoredChatSamplePrompts()).toEqual(rows)
  })

  it('新キーが Zod 検証に通らない配列のときはキーを捨て INITIAL＋旧キーで移行する', () => {
    localStorage.setItem(CHAT_SAMPLE_PROMPTS_STORAGE_KEY, JSON.stringify([{ id: '', label: 'x', text: 'y' }]))
    const rows = readStoredChatSamplePrompts()
    expect(rows).toEqual([...INITIAL_CHAT_SAMPLE_PROMPTS])
  })
})
