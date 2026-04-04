const DOUBLE_NEWLINE = '\n\n'

/**
 * サンプル質問のうち選択されたものを、一覧の定義順で本文だけ抽出し `\n\n` で連結して下書きへ追記する。
 */
export function appendSelectedChatSampleTextsToDraft(
  currentDraft: string,
  orderedItems: readonly { id: string; text: string }[],
  selectedIds: ReadonlySet<string>,
): string {
  const texts = orderedItems
    .filter((item) => selectedIds.has(item.id))
    .map((item) => item.text.trim())
    .filter((t) => t.length > 0)
  const block = texts.join(DOUBLE_NEWLINE)
  if (!block) {
    return currentDraft
  }
  const trimmedDraft = currentDraft.trimEnd()
  if (!trimmedDraft) {
    return block
  }
  return `${trimmedDraft}${DOUBLE_NEWLINE}${block}`
}
