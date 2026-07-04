const LLM_HEADING_LINE = '## LLM 要約'

/** ダイジェスト本文から ``## LLM 要約`` セクション以降を除去する。 */
export function stripLlmDigestSection(markdown: string): string {
  const lines = markdown.split(/\r?\n/)
  const idx = lines.findIndex((line) => line.trim() === LLM_HEADING_LINE)
  if (idx === -1) {
    return markdown
  }
  return lines.slice(0, idx).join('\n').trimEnd()
}
