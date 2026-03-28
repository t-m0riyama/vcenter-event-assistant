/**
 * GFM の pipe 表は「ヘッダ行の直後に区切り行（`| --- |`）」が必須。
 * ヘッダ・区切り・データのいずれかの間に空行があると表が分断され、複数の表や生テキスト行になる。
 * 保存済み Markdown を補正する。
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
 * この pipe 行の直後（空行を除く）が区切り行なら、新しい表の先頭行とみなす。
 * 連続した表のあいだの空行はこの行を境に残す。
 */
function isStartOfNewPipeTable(lines: readonly string[], pipeLineIdx: number): boolean {
  const line = lines[pipeLineIdx]
  if (line === undefined || !isPipeTableRow(line) || isPipeTableDelimiterRow(line)) {
    return false
  }
  const nextNonBlank = indexOfNextNonBlankLine(lines, pipeLineIdx + 1)
  if (nextNonBlank >= lines.length) {
    return false
  }
  return isPipeTableDelimiterRow(lines[nextNonBlank]!)
}

/**
 * 区切り行が欠けている pipe 表を補う。ヘッダとデータの間の空行は削除して 1 つの表にまとめる。
 */
function insertMissingDelimiterRows(markdown: string): string {
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

/**
 * 同一表内で pipe 行と pipe 行のあいだに空行があると GFM では表が終了する。
 * 次の pipe 行が「新しい表の先頭」（直後に区切り行）でないときだけ空行を除去する。
 */
function removeBlankLinesBetweenPipeTableRows(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    if (line.trim() === '' && out.length > 0) {
      const prev = out[out.length - 1]!
      const j = indexOfNextNonBlankLine(lines, i)
      if (j < lines.length) {
        const next = lines[j]!
        if (
          isPipeTableRow(prev) &&
          isPipeTableRow(next) &&
          countPipeColumns(prev) === countPipeColumns(next) &&
          !isStartOfNewPipeTable(lines, j)
        ) {
          i = j
          continue
        }
      }
    }
    out.push(line)
    i += 1
  }
  return out.join('\n')
}

export function repairPipeTablesForGfm(markdown: string): string {
  // 先に空行を詰める。空行の直後の pipe 行をヘッダと誤認して区切り行を差し込むのを防ぐ。
  return insertMissingDelimiterRows(removeBlankLinesBetweenPipeTableRows(markdown))
}
