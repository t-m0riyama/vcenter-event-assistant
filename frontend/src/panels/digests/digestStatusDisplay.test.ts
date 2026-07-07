import { describe, expect, it } from 'vitest'

import type { DigestRead } from '../../api/schemas'
import { digestStatusLabel, resolveDigestEffectiveStatus } from './digestStatusDisplay'

const base: DigestRead = {
  id: 1,
  period_start: '2026-03-27T00:00:00Z',
  period_end: '2026-03-28T00:00:00Z',
  kind: 'daily',
  body_markdown: '# T',
  status: 'ok',
  error_message: null,
  llm_model: null,
  created_at: '2026-03-28T01:00:00Z',
}

describe('resolveDigestEffectiveStatus', () => {
  it('maps legacy ok + error_message to ok_llm_failed', () => {
    expect(
      resolveDigestEffectiveStatus({
        ...base,
        status: 'ok',
        error_message: 'LLM 要約は省略（timeout）',
      }),
    ).toBe('ok_llm_failed')
  })

  it('keeps ok_llm_failed as-is', () => {
    expect(
      resolveDigestEffectiveStatus({
        ...base,
        status: 'ok_llm_failed',
        error_message: 'LLM 要約は省略（timeout）',
      }),
    ).toBe('ok_llm_failed')
  })
})

describe('digestStatusLabel', () => {
  it('returns Japanese labels for known statuses', () => {
    expect(digestStatusLabel('ok')).toBe('正常')
    expect(digestStatusLabel('ok_llm_failed')).toBe('LLM 失敗')
    expect(digestStatusLabel('error')).toBe('エラー')
  })
})
