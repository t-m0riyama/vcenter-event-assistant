import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { collectionErrorGuidance, collectionErrorMessage } from './collectionErrorMessage'

// バックエンドが記録しうる失敗の文字列。tests/test_collection_error_records.py が書き出し、
// バックエンドの型や文言が増えると、そちらのテストが一覧の更新を求める。
const here = dirname(fileURLToPath(import.meta.url))
const records = JSON.parse(readFileSync(join(here, 'collectionErrorRecords.json'), 'utf-8')) as Record<string, string[]>
const { japanese = [], ...typed } = records
const typedRecords = Object.values(typed).flat()

describe('バックエンドが記録しうる失敗の文字列', () => {
  it('一覧が揃っている', () => {
    expect(Object.keys(typed).sort()).toEqual(['inventory_reads', 'representative', 'safe_detail', 'worker'])
    expect(typedRecords.length).toBeGreaterThan(30)
    expect(japanese.length).toBeGreaterThan(0)
  })

  it.each(typedRecords)('%s に種類ごとの案内がある', (record) => {
    expect(collectionErrorGuidance(record)).toBeDefined()
  })

  it.each(japanese)('型名の無い日本語の記録 %s はそのまま出す', (record) => {
    expect(collectionErrorMessage(record)).toBe(record)
  })
})
