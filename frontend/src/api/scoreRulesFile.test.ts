import { describe, expect, it } from 'vitest'
import {
  buildScoreRulesExportPayload,
  eventScoreRulesFileSchema,
} from './schemas'

describe('eventScoreRulesFileSchema', () => {
  it('accepts valid export shape', () => {
    const raw = {
      format: 'vea-event-score-rules',
      version: 1,
      exportedAt: '2026-03-22T00:00:00.000Z',
      rules: [{ event_type: 'vim.event.A', score_delta: 5 }],
    }
    expect(eventScoreRulesFileSchema.parse(raw).rules[0].event_type).toBe('vim.event.A')
  })

  it('rejects duplicate event_type in rules', () => {
    const raw = {
      format: 'vea-event-score-rules',
      version: 1,
      rules: [
        { event_type: 'vim.event.A', score_delta: 1 },
        { event_type: 'vim.event.A', score_delta: 2 },
      ],
    }
    expect(() => eventScoreRulesFileSchema.parse(raw)).toThrow()
  })
})

describe('buildScoreRulesExportPayload', () => {
  it('builds validated file payload', () => {
    const p = buildScoreRulesExportPayload([
      { id: 1, event_type: 'vim.event.X', score_delta: 3 },
    ])
    expect(p.format).toBe('vea-event-score-rules')
    expect(p.rules).toEqual([{ event_type: 'vim.event.X', score_delta: 3 }])
  })
})
