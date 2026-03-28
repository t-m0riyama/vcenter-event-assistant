import { describe, expect, it } from 'vitest'
import { stripLlmDigestSection } from './stripLlmDigestSection'

describe('stripLlmDigestSection', () => {
  it('returns full markdown when heading is absent', () => {
    const md = '# Title\n\n| a | b |\n|---|---|'
    expect(stripLlmDigestSection(md)).toBe(md)
  })

  it('truncates before first ## LLM 要約 line', () => {
    const md = '# T\n\n## LLM 要約\n\n- 要点'
    expect(stripLlmDigestSection(md)).toBe('# T')
  })

  it('handles CRLF', () => {
    const md = '# T\r\n\r\n## LLM 要約\r\n\r\nx'
    expect(stripLlmDigestSection(md)).toBe('# T')
  })

  it('returns empty string when heading is first line', () => {
    expect(stripLlmDigestSection('## LLM 要約\n\nx')).toBe('')
  })
})
