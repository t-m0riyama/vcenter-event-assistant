import type { DigestRead } from '../../api/schemas'
import { repairPipeTablesForGfm } from './repairPipeTablesForGfm'
import { stripLlmDigestSection } from './stripLlmDigestSection'

/**
 * ダイジェスト本文を画面表示・ファイル出力で共通利用する Markdown に整形する。
 * `llm_model` が無い場合は `## LLM 要約` ブロックを含めない。
 */
export function getDigestBodyMarkdownForDisplay(d: DigestRead): string {
  const raw = d.llm_model != null ? d.body_markdown : stripLlmDigestSection(d.body_markdown)
  return repairPipeTablesForGfm(raw)
}
