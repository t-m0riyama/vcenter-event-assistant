import { describe, expect, it } from 'vitest'
import { repairPipeTablesForGfm } from './repairPipeTablesForGfm'

describe('repairPipeTablesForGfm', () => {
  it('inserts delimiter between header and first data row when missing', () => {
    const md = [
      '## 上位イベント種別',
      '',
      '| 種別 | 件数 | max notable |',
      '| `vim.event.X` | 1730 | 0 |',
      '',
      'footer',
    ].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    expect(fixed).toContain('| --- | --- | --- |')
    expect(fixed.split('\n').slice(2, 6).join('\n')).toBe(
      ['| 種別 | 件数 | max notable |', '| --- | --- | --- |', '| `vim.event.X` | 1730 | 0 |', ''].join('\n'),
    )
  })

  it('does not duplicate when delimiter already exists', () => {
    const md = ['| a | b |', '| --- | --- |', '| 1 | 2 |'].join('\n')
    expect(repairPipeTablesForGfm(md)).toBe(md)
  })

  it('leaves non-table pipes alone when column counts mismatch', () => {
    const md = ['| a | b |', '| only one col |'].join('\n')
    expect(repairPipeTablesForGfm(md)).toBe(md)
  })
})
