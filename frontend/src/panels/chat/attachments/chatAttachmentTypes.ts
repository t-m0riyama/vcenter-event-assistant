/** チャット添付の型と既定値（サーバの ChatAttachment と対応）。 */

export type ChatAttachmentKind = 'text' | 'image'

/** API に送る 1 添付。テキストは抽出済み本文、画像は縮小済み base64。 */
export type ChatAttachmentPayload = {
  kind: ChatAttachmentKind
  filename: string
  media_type: string
  text?: string
  data_base64?: string
  truncated?: boolean
}

/** 入力欄が保持する添付 1 件の状態。 */
export type ChatAttachmentDraft = {
  id: string
  filename: string
  sizeBytes: number
  kind: ChatAttachmentKind | 'unsupported'
  status: 'reading' | 'ready' | 'error'
  /** status='error' のときの理由（利用者に表示する） */
  error?: string
  /** status='ready' のときの送信内容 */
  payload?: ChatAttachmentPayload
  /** 画像のサムネイル用データ URL */
  previewUrl?: string
}

/** サーバから受け取る添付の上限。/api/config 取得前の暫定値でもある。 */
export type ChatAttachmentLimits = {
  maxFiles: number
  maxFileBytes: number
  maxTextChars: number
  /** LLM プロバイダが画像を扱えるか */
  imagesAvailable: boolean
}

export const DEFAULT_CHAT_ATTACHMENT_LIMITS: ChatAttachmentLimits = {
  maxFiles: 5,
  maxFileBytes: 10 * 1024 * 1024,
  maxTextChars: 100_000,
  imagesAvailable: false,
}
