import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { parseJsonImportFile, takeFirstImportFile } from './parseJsonImportFile'

describe('parseJsonImportFile', () => {
  const schema = z.object({ format: z.literal('test'), version: z.number(), items: z.array(z.string()) })

  it('有効な JSON ファイルをパースして schema 検証する', async () => {
    const file = new File(
      [JSON.stringify({ format: 'test', version: 1, items: ['a'] })],
      'rules.json',
      { type: 'application/json' },
    )
    const result = await parseJsonImportFile(file, schema)
    expect(result).toEqual({
      ok: true,
      data: { format: 'test', version: 1, items: ['a'] },
    })
  })

  it('JSON 構文エラーは ok: false で error を返す', async () => {
    const file = new File(['{'], 'bad.json', { type: 'application/json' })
    const result = await parseJsonImportFile(file, schema)
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error).toBeInstanceOf(SyntaxError)
    }
  })

  it('Zod 検証失敗は ok: false で error を返す', async () => {
    const file = new File(
      [JSON.stringify({ format: 'wrong', version: 1, items: [] })],
      'bad.json',
      { type: 'application/json' },
    )
    const result = await parseJsonImportFile(file, schema)
    expect(result.ok).toBe(false)
  })
})

describe('takeFirstImportFile', () => {
  it('先頭ファイルを返し input.value をクリアする', () => {
    const input = document.createElement('input')
    input.type = 'file'
    const file = new File(['{}'], 'a.json')
    const dt = new DataTransfer()
    dt.items.add(file)
    input.files = dt.files

    const taken = takeFirstImportFile(input)
    expect(taken).toBe(file)
    expect(input.value).toBe('')
  })

  it('ファイル未選択のとき null を返す', () => {
    const input = document.createElement('input')
    input.type = 'file'
    expect(takeFirstImportFile(input)).toBeNull()
  })
})
