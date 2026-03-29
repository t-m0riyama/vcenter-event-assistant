import { describe, expect, it } from 'vitest'
import { getDigestBodyMarkdownForDisplay } from './getDigestBodyMarkdownForDisplay'
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

describe('getDigestBodyMarkdownForDisplay', () => {
  it('excludes ## LLM 要約 section when llm_model is null', () => {
    const body = '# Title\n\n## LLM 要約\n\n- point'
    const out = getDigestBodyMarkdownForDisplay(
      digestFixture({ llm_model: null, body_markdown: body }),
    )
    expect(out).not.toContain('## LLM 要約')
    expect(out).not.toContain('point')
  })

  it('keeps ## LLM 要約 section when llm_model is set', () => {
    const body = '# Title\n\n## LLM 要約\n\n- point'
    const out = getDigestBodyMarkdownForDisplay(
      digestFixture({ llm_model: 'gpt-4', body_markdown: body }),
    )
    expect(out).toContain('## LLM 要約')
    expect(out).toContain('point')
  })
})
