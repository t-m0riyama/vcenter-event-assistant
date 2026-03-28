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
    expect(fixed).not.toMatch(/\| 種別 \|[^\n]+\n\n\| `vim/) // ヘッダとデータの間に空行を残さない
  })

  it('removes blank lines between header and data and inserts delimiter', () => {
    const md = ['| a | b |', '', '', '| 1 | 2 |'].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    expect(fixed.split('\n')).toEqual(['| a | b |', '| --- | --- |', '| 1 | 2 |'])
  })

  it('does not duplicate when delimiter already exists', () => {
    const md = ['| a | b |', '| --- | --- |', '| 1 | 2 |'].join('\n')
    expect(repairPipeTablesForGfm(md)).toBe(md)
  })

  it('does not insert delimiter between two data rows', () => {
    const md = ['| a | b |', '| --- | --- |', '| 1 | 2 |', '| 3 | 4 |'].join('\n')
    expect(repairPipeTablesForGfm(md)).toBe(md)
  })

  it('leaves non-table pipes alone when column counts mismatch', () => {
    const md = ['| a | b |', '| only one col |'].join('\n')
    expect(repairPipeTablesForGfm(md)).toBe(md)
  })
})
