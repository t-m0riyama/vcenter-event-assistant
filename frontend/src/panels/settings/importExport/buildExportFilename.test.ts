import { describe, expect, it } from 'vitest'

import { buildVeaExportFilename } from './buildExportFilename'

describe('buildVeaExportFilename', () => {
  it('プレフィックスと UTC 日付（YYYY-MM-DD）で .json ファイル名を組み立てる', () => {
    const name = buildVeaExportFilename('vea-score-rules', new Date('2026-03-22T15:30:00Z'))
    expect(name).toBe('vea-score-rules-2026-03-22.json')
  })
})
