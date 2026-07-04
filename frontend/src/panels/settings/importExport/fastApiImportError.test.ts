import { describe, expect, it } from 'vitest'

import { formatImportApiError } from './fastApiImportError'

describe('formatImportApiError', () => {
  it('ネットワーク失敗を日本語に変換する', () => {
    expect(formatImportApiError(new Error('Failed to fetch'))).toContain('ネットワーク')
  })

  it('既知 detail を apiDetailJa で置換する', () => {
    const err = new Error('400 {"detail":"duplicate event_type in rules"}')
    const msg = formatImportApiError(err, {
      apiDetailJa: {
        'duplicate event_type in rules': '重複しています',
      },
    })
    expect(msg).toBe('重複しています')
  })

  it('422 は format422Message に委譲する', () => {
    const err = new Error(
      '422 {"detail":[{"type":"string_type","loc":["body","rules",0,"event_type"],"msg":"Input should be a valid string"}]}',
    )
    const msg = formatImportApiError(err, {
      format422Message: (detail) => `422:${detail ?? 'none'}`,
    })
    expect(msg).toContain('422:')
    expect(msg).toContain('event_type')
  })

  it('500 以上はサーバーエラーメッセージを返す', () => {
    const err = new Error('503 {"detail":"unavailable"}')
    expect(formatImportApiError(err)).toContain('サーバー側でエラー')
  })
})
