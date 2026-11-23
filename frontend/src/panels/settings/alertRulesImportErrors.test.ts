import { describe, expect, it } from 'vitest'
import { formatAlertRulesImportApiError } from './alertRulesImportErrors'

describe('アラートルールのインポートエラー', () => {
  it.each([
    'unknown event_pattern pattern_ids: future, removed',
    [{ loc: ['body', 'rules', 1], msg: 'Value error, unknown event_pattern pattern_ids: future, removed' }],
  ])('HTTP 422 の詳細から未定義の障害パターン ID を取り出す', (detail) => {
    const error = new Error(`422 Unprocessable Content ${JSON.stringify({ detail })}`)
    expect(formatAlertRulesImportApiError(error)).toBe(
      '未定義の障害パターン ID が指定されています（future, removed）。',
    )
  })
})
