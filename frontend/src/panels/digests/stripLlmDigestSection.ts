/** ダイジェスト本文から、最初の行 `## LLM 要約` より前の部分だけを返す（要約ブロックを表示しないとき用）。 */
const LLM_HEADING_LINE = '## LLM 要約'

export function stripLlmDigestSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const idx = lines.findIndex((line) => line.trim() === LLM_HEADING_LINE)
  if (idx === -1) {
    return markdown
  }
  return lines.slice(0, idx).join('\n').trimEnd()
}
