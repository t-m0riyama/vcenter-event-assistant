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

  it('removes blank lines between data rows so the table stays one GFM block', () => {
    const md = [
      '| 種別 | 件数 |',
      '| --- | --- |',
      '| vim.event.A | 1 |',
      '',
      '| vim.event.B | 2 |',
    ].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    expect(fixed).not.toMatch(/\| vim.event.A \|[^\n]+\n\n\| vim.event.B/)
    expect(fixed.split('\n').filter((l) => l.trim() === '').length).toBe(0)
  })

  it('keeps blank line between two separate pipe tables (next row is a new header)', () => {
    const md = [
      '| a | b |',
      '| --- | --- |',
      '| 1 | 2 |',
      '',
      '| c | d |',
      '| --- | --- |',
      '| 3 | 4 |',
    ].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    const parts = fixed.split(/\n\n/)
    expect(parts.length).toBeGreaterThanOrEqual(2)
    expect(fixed).toContain('| c | d |')
  })

  it('inserts delimiter and joins header to data when host-style blank appears (no separator row)', () => {
    const md = [
      '## ホスト CPU',
      '',
      '| vCenter | ホスト | % | サンプル時刻 |',
      '',
      '| 7ecd | mini5 | 20.2 | 2026-03-27T08:03:23+00:00 |',
    ].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    expect(fixed).toMatch(/\| vCenter \|[^\n]+\n\| --- \|/)
    expect(fixed).not.toMatch(/\| vCenter \|[^\n]+\n\n\| 7ecd/)
  })

  it('merges stored digest shape: delimiter then blank lines then every data row separated by blanks (1.md sample)', () => {
    const md = [
      '## 上位イベント種別（件数順）',
      '',
      '| 種別 | 件数 | max notable |',
      '|------|------|-------------|',
      '',
      '',
      '| `vim.event.UserLogoutSessionEvent` | 1715 | 0 |',
      '',
      '| `vim.event.UserLoginSessionEvent` | 1713 | 0 |',
      '',
      '| `vim.event.EventEx` | 8 | 0 |',
      '',
      '## 要注意イベント（スコア上位）',
      '',
      '- note',
    ].join('\n')
    const fixed = repairPipeTablesForGfm(md)
    const start = fixed.indexOf('| 種別 |')
    const end = fixed.indexOf('## 要注意')
    expect(start).toBeGreaterThanOrEqual(0)
    expect(end).toBeGreaterThan(start)
    const chunk = fixed.slice(start, end)
    expect(chunk).not.toMatch(/\|\s*\n\n\|/)
  })
})
