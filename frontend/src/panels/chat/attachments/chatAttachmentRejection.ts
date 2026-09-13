import type { ChatAttachmentKind, ChatAttachmentLimits } from './chatAttachmentTypes'

/** 1MB 未満も読めるサイズ表記。 */
export function formatAttachmentSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`
  return `${bytes}B`
}

/**
 * 添付を受け付けられない理由（受け付けられるときは null）。
 *
 * `alreadyAttached` は既に入力欄にある件数。件数上限の判定に使う。
 */
export function chatAttachmentRejectionReason(
  file: { name: string; size: number },
  kind: ChatAttachmentKind | 'unsupported',
  limits: ChatAttachmentLimits,
  alreadyAttached: number,
): string | null {
  if (limits.maxFiles <= 0) {
    return 'ファイルの添付は無効化されています'
  }
  if (alreadyAttached >= limits.maxFiles) {
    return `添付できるのは ${limits.maxFiles} 件までです`
  }
  if (kind === 'unsupported') {
    return '対応していない形式です（テキスト系ファイルと PNG / JPEG 画像のみ）'
  }
  if (kind === 'image' && !limits.imagesAvailable) {
    return '現在の LLM プロバイダは画像を扱えません'
  }
  if (file.size > limits.maxFileBytes) {
    return `ファイルが大きすぎます（上限 ${formatAttachmentSize(limits.maxFileBytes)}）`
  }
  if (file.size === 0) {
    return '中身が空のファイルです'
  }
  return null
}
