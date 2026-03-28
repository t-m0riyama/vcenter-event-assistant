/**
 * GFM の pipe 表は「ヘッダ行の直後に区切り行（`| --- |`）」が必須。
 * ヘッダとデータの間に空行があるとブロックが分断され、データ行が表にならない。
 * また区切り行が無いとデータ行は生テキストになる。保存済み Markdown を補正する。
 */

function isPipeTableRow(line: string): boolean {
  const t = line.trim()
  return t.startsWith('|') && t.endsWith('|') && (t.match(/\|/g)?.length ?? 0) >= 2
}

/** GFM の alignment 行（`| :--- | ---: |` 等） */
function isPipeTableDelimiterRow(line: string): boolean {
  const t = line.trim()
  if (!t.startsWith('|') || !t.endsWith('|')) {
    return false
  }
  const cells = t
    .slice(1, -1)
    .split('|')
    .map((c) => c.trim())
  if (cells.length === 0) {
    return false
  }
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell))
}

function countPipeColumns(line: string): number {
  const t = line.trim()
  const parts = t.split('|')
  if (parts.length < 2) {
    return 0
  }
  return parts.slice(1, -1).length
}

function makeDelimiterRow(columnCount: number): string {
  if (columnCount < 1) {
    return '| --- |'
  }
  return `|${Array.from({ length: columnCount }, () => ' --- ').join('|')}|`
}

/**
 * 表の「先頭行」だけをヘッダ候補とする（tbody のデータ行同士の間に区切りを入れない）。
 */
function isLikelyTableHeaderRow(lines: readonly string[], i: number): boolean {
  const line = lines[i]
  if (line === undefined || !isPipeTableRow(line) || isPipeTableDelimiterRow(line)) {
    return false
  }
  if (i === 0) {
    return true
  }
  const prev = lines[i - 1]
  if (prev === undefined) {
    return true
  }
  const prevTrim = prev.trim()
  if (prevTrim === '') {
    return true
  }
  if (prevTrim.startsWith('#')) {
    return true
  }
  if (isPipeTableDelimiterRow(prev)) {
    return false
  }
  if (isPipeTableRow(prev) && !isPipeTableDelimiterRow(prev)) {
    return false
  }
  return true
}

function indexOfNextNonBlankLine(lines: readonly string[], start: number): number {
  let j = start
  while (j < lines.length) {
    const s = lines[j]?.trim() ?? ''
    if (s !== '') {
      return j
    }
    j += 1
  }
  return lines.length
}

/**
 * 区切り行が欠けている pipe 表を補う。ヘッダとデータの間の空行は削除して 1 つの表にまとめる。
 */
export function repairPipeTablesForGfm(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  let i = 0
  while (i < lines.length) {
    if (!isLikelyTableHeaderRow(lines, i)) {
      i += 1
      continue
    }
    const header = lines[i]!
    const colCount = countPipeColumns(header)
    if (colCount < 2) {
      i += 1
      continue
    }
    const j = indexOfNextNonBlankLine(lines, i + 1)
    if (j >= lines.length) {
      i += 1
      continue
    }
    const rowAfterBlanks = lines[j]!
    if (!isPipeTableRow(rowAfterBlanks) || isPipeTableDelimiterRow(rowAfterBlanks)) {
      i += 1
      continue
    }
    if (countPipeColumns(rowAfterBlanks) !== colCount) {
      i += 1
      continue
    }
    const immediate = lines[i + 1]
    if (immediate !== undefined && isPipeTableDelimiterRow(immediate)) {
      i += 1
      continue
    }
    lines.splice(i + 1, j - i - 1, makeDelimiterRow(colCount))
    i += 2
  }
  return lines.join('\n')
}
