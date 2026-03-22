import { describe, expect, it } from 'vitest'
import { eventScoreRulesFileSchema } from '../../api/schemas'
import { formatScoreRulesFileParseError, formatScoreRulesImportApiError } from './scoreRulesImportErrors'

describe('formatScoreRulesFileParseError', () => {
  it('maps JSON SyntaxError to Japanese', () => {
    const msg = formatScoreRulesFileParseError(new SyntaxError('Unexpected token'))
    expect(msg).toContain('JSON')
  })

  it('maps duplicate event_type in Zod to Japanese', () => {
    try {
      eventScoreRulesFileSchema.parse({
        format: 'vea-event-score-rules',
        version: 1,
        rules: [
          { event_type: 'a', score_delta: 1 },
          { event_type: 'a', score_delta: 2 },
        ],
      })
      expect.fail('should throw')
    } catch (e) {
      expect(formatScoreRulesFileParseError(e)).toContain('重複')
    }
  })

  it('maps invalid_type for event_type (e.g. number) to Japanese without raw JSON', () => {
    try {
      eventScoreRulesFileSchema.parse({
        format: 'vea-event-score-rules',
        version: 1,
        rules: [{ event_type: 123 as unknown as string, score_delta: 1 }],
      })
      expect.fail('should throw')
    } catch (e) {
      const msg = formatScoreRulesFileParseError(e)
      expect(msg).not.toMatch(/^\s*\[/)
      expect(msg).toContain('文字列')
      expect(msg).toContain('event_type')
    }
  })

  it('maps Zod message that is JSON array string (no ZodError instance) to Japanese', () => {
    const raw =
      '[ { "expected": "string", "code": "invalid_type", "path": [ "rules", 0, "event_type" ], "message": "Invalid input" } ]'
    expect(formatScoreRulesFileParseError(new Error(raw))).toContain('二重引用符')
  })
})

describe('formatScoreRulesImportApiError', () => {
  it('maps duplicate event_type API detail to Japanese', () => {
    const err = new Error(
      '400 {"detail":"duplicate event_type in rules"}',
    )
    expect(formatScoreRulesImportApiError(err)).toContain('重複')
  })

  it('maps network failure', () => {
    expect(formatScoreRulesImportApiError(new Error('Failed to fetch'))).toContain('ネットワーク')
  })

  it('maps 422 with event_type in detail to Japanese', () => {
    const err = new Error(
      '422 {"detail":[{"type":"string_type","loc":["body","rules",0,"event_type"],"msg":"Input should be a valid string"}]}',
    )
    const msg = formatScoreRulesImportApiError(err)
    expect(msg).toContain('event_type')
    expect(msg).not.toMatch(/Input should be/)
  })
})
