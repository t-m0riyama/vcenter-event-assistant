const DOUBLE_NEWLINE = '\n\n'

/**
 * サンプル質問の本文を下書き末尾へ追記する。
 * 既存下書きが空でなければ末尾を `trimEnd` してから `\n\n` で区切る。本文は `trim` し、空なら変更しない。
 */
export function appendChatSampleTextToDraft(currentDraft: string, text: string): string {
  const block = text.trim()
  if (!block) {
    return currentDraft
  }
  const trimmedDraft = currentDraft.trimEnd()
  if (!trimmedDraft) {
    return block
  }
  return `${trimmedDraft}${DOUBLE_NEWLINE}${block}`
}
