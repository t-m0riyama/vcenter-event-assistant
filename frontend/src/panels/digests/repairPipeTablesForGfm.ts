/**
 * GFM の pipe 表は「ヘッダ行の直後に区切り行（`| --- |`）」が必須。
 * 欠けると後続の `| ... |` 行が表セルにならず、そのままテキストとして表示される。
 * 保存済み Markdown に区切り行が無いケースを補う。
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
 * 「区切り行の無い pipe 表」の直後に区切り行を挿入する。
 * ヘッダ行の次行が区切り行でなく、かつ次行も pipe 行で列数が一致するときに限る。
 */
export function repairPipeTablesForGfm(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const out: string[] = []
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i] ?? ''
    out.push(line)
    const next = lines[i + 1]
    if (next === undefined) {
      continue
    }
    if (
      isPipeTableRow(line) &&
      !isPipeTableDelimiterRow(line) &&
      isPipeTableRow(next) &&
      !isPipeTableDelimiterRow(next)
    ) {
      const c0 = countPipeColumns(line)
      const c1 = countPipeColumns(next)
      if (c0 >= 2 && c0 === c1) {
        out.push(makeDelimiterRow(c0))
      }
    }
  }
  return out.join('\n')
}
