import type { ChatAttachmentPayload } from './chatAttachmentTypes'

/** 抽出したテキストを上限文字数に収める。 */
export function truncateAttachmentText(
  text: string,
  maxChars: number,
): { text: string; truncated: boolean } {
  if (text.length <= maxChars) return { text, truncated: false }
  return { text: text.slice(0, maxChars), truncated: true }
}

/**
 * テキストファイルを読み取り、送信用ペイロードにする。
 * 読み取りはブラウザ側で完結させ、サーバに抽出処理を持ち込まない。
 */
export async function readTextAttachment(
  file: File,
  maxChars: number,
): Promise<ChatAttachmentPayload> {
  const raw = await file.text()
  const { text, truncated } = truncateAttachmentText(raw, maxChars)
  if (!text.trim()) {
    throw new Error('中身が空のファイルです')
  }
  return {
    kind: 'text',
    filename: file.name,
    media_type: file.type || 'text/plain',
    text,
    truncated,
  }
}
