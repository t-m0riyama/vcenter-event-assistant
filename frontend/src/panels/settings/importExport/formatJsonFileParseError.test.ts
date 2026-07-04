import { describe, expect, it } from 'vitest'
import { ZodError } from 'zod'

import { formatJsonFileParseError } from './formatJsonFileParseError'

describe('formatJsonFileParseError', () => {
  const describeIssues = (issues: readonly { message: string }[]) =>
    issues.length === 0 ? 'empty' : `domain:${issues[0].message}`

  it('SyntaxError を JSON 向けの日本語メッセージに変換する', () => {
    const msg = formatJsonFileParseError(new SyntaxError('x'), describeIssues)
    expect(msg).toContain('JSON')
  })

  it('ZodError を describeZodIssues に委譲する', () => {
    const err = new ZodError([{ code: 'custom', message: 'bad', path: [] }])
    expect(formatJsonFileParseError(err, describeIssues)).toBe('domain:bad')
  })

  it('Error.message が Zod issues JSON 配列のとき describeZodIssues に委譲する', () => {
    const raw =
      '[ { "expected": "string", "code": "invalid_type", "path": [ "rules", 0, "event_type" ], "message": "Invalid input" } ]'
    expect(formatJsonFileParseError(new Error(raw), describeIssues)).toBe('domain:Invalid input')
  })
})
