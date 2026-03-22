/** 折りたたみ一覧のプレビュー用に連結するフィールド（action_required は含めない） */
export type EventTypeGuidePreviewFields = {
  readonly general_meaning: string
  readonly typical_causes: string
  readonly remediation: string
}

export type FormatEventTypeGuideCollapsedPreviewOptions = {
  /** 論理省略の最大文字数（末尾の `…` を含む）。既定 200 */
  readonly maxChars?: number
}

const DEFAULT_MAX_CHARS = 200
const ELLIPSIS = '…'
const EMPTY_PLACEHOLDER = '（本文なし）'

/**
 * 設定パネル一覧の折りたたみ行向けに、意味・原因・対処を1行のプレビュー文字列にまとめる。
 * 空の項目はスキップし、すべて空ならプレースホルダを返す。`maxChars` を超える場合は末尾を `…` で省略する。
 */
export function formatEventTypeGuideCollapsedPreview(
  fields: EventTypeGuidePreviewFields,
  options?: FormatEventTypeGuideCollapsedPreviewOptions,
): string {
  const maxChars = options?.maxChars ?? DEFAULT_MAX_CHARS
  const parts: string[] = []
  const m = fields.general_meaning.trim()
  const c = fields.typical_causes.trim()
  const r = fields.remediation.trim()
  if (m) parts.push(`意味: ${m}`)
  if (c) parts.push(`原因: ${c}`)
  if (r) parts.push(`対処: ${r}`)
  const joined = parts.length > 0 ? parts.join(' / ') : EMPTY_PLACEHOLDER
  return truncateWithEllipsis(joined, maxChars)
}

function truncateWithEllipsis(s: string, maxChars: number): string {
  if (s.length <= maxChars) return s
  const headLen = Math.max(0, maxChars - ELLIPSIS.length)
  return s.slice(0, headLen) + ELLIPSIS
}
