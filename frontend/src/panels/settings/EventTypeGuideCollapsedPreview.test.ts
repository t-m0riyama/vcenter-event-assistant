import { describe, expect, it } from 'vitest'
import { formatEventTypeGuideCollapsedPreview } from './EventTypeGuideCollapsedPreview'

describe('formatEventTypeGuideCollapsedPreview', () => {
  it('3 フィールドをラベル付きで連結する', () => {
    const s = formatEventTypeGuideCollapsedPreview(
      { general_meaning: 'a', typical_causes: 'b', remediation: 'c' },
      { maxChars: 200 },
    )
    expect(s).toContain('意味: a')
    expect(s).toContain('原因: b')
    expect(s).toContain('対処: c')
    expect(s).toContain(' / ')
  })

  it('空の項目はスキップする', () => {
    const s = formatEventTypeGuideCollapsedPreview(
      { general_meaning: '  x  ', typical_causes: '', remediation: '  ' },
      { maxChars: 200 },
    )
    expect(s).toBe('意味: x')
  })

  it('すべて空ならプレースホルダ', () => {
    expect(
      formatEventTypeGuideCollapsedPreview(
        { general_meaning: '', typical_causes: '  ', remediation: '' },
        { maxChars: 200 },
      ),
    ).toBe('（本文なし）')
  })

  it('maxChars を超えたら末尾が … になる', () => {
    const long = 'あ'.repeat(50)
    const s = formatEventTypeGuideCollapsedPreview(
      { general_meaning: long, typical_causes: '', remediation: '' },
      { maxChars: 20 },
    )
    expect(s.endsWith('…')).toBe(true)
    expect(s.length).toBe(20)
  })
})
