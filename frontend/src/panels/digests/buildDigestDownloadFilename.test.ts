import { describe, expect, it } from 'vitest'
import { buildDigestDownloadFilename } from './buildDigestDownloadFilename'
import type { DigestRead } from '../../api/schemas'

function digestFixture(overrides: Partial<DigestRead>): DigestRead {
  return {
    id: 1,
    period_start: '2026-03-28T00:00:00Z',
    period_end: '2026-03-29T00:00:00Z',
    kind: 'daily',
    body_markdown: '',
    status: 'ok',
    error_message: null,
    llm_model: null,
    created_at: '2026-03-29T12:00:00Z',
    ...overrides,
  }
}

describe('buildDigestDownloadFilename', () => {
  it('ends with .md and contains id and sanitized kind', () => {
    const name = buildDigestDownloadFilename(digestFixture({ id: 42, kind: 'daily' }))
    expect(name).toMatch(/^digest-42-daily-2026-03-28\.md$/)
  })

  it('sanitizes kind for filesystem safety', () => {
    const name = buildDigestDownloadFilename(digestFixture({ id: 1, kind: 'we/ird:k ind' }))
    expect(name).not.toMatch(/[\\/]/)
    expect(name.endsWith('.md')).toBe(true)
    expect(name).toMatch(/^digest-1-.+-2026-03-28\.md$/)
  })

  it('uses period_start UTC date as YYYY-MM-DD', () => {
    const name = buildDigestDownloadFilename(
      digestFixture({ period_start: '2025-12-31T15:30:00Z', kind: 'weekly' }),
    )
    expect(name).toContain('2025-12-31')
  })
})
