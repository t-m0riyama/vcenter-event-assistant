import type { ChatAttachmentKind } from './chatAttachmentTypes'

/** 添付として受け付けるテキストの拡張子。 */
const TEXT_EXTENSIONS = [
  '.log',
  '.txt',
  '.csv',
  '.tsv',
  '.json',
  '.md',
  '.yaml',
  '.yml',
  '.xml',
  '.conf',
  '.ini',
] as const

/** 添付として受け付ける画像の MIME。サーバの allowlist と一致させる。 */
const IMAGE_MEDIA_TYPES = ['image/png', 'image/jpeg'] as const

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg'] as const

/** `input[type=file]` の accept 属性値。 */
export const CHAT_ATTACHMENT_ACCEPT = [...TEXT_EXTENSIONS, ...IMAGE_EXTENSIONS, 'text/*'].join(',')

function hasExtension(filename: string, extensions: readonly string[]): boolean {
  const lower = filename.toLowerCase()
  return extensions.some((ext) => lower.endsWith(ext))
}

/**
 * ファイルを添付の種別に分類する。MIME が当てにならないブラウザ・OS があるため
 * 拡張子も見る（`.log` は多くの環境で MIME が空になる）。
 */
export function classifyChatAttachmentFile(file: {
  name: string
  type: string
}): ChatAttachmentKind | 'unsupported' {
  const mime = (file.type || '').toLowerCase()
  if ((IMAGE_MEDIA_TYPES as readonly string[]).includes(mime)) return 'image'
  if (mime.startsWith('image/')) return 'unsupported'
  if (mime.startsWith('text/') || mime === 'application/json') return 'text'
  if (hasExtension(file.name, IMAGE_EXTENSIONS)) return 'image'
  if (hasExtension(file.name, TEXT_EXTENSIONS)) return 'text'
  return 'unsupported'
}

/** 画像添付として送る MIME（判定できないときは PNG 扱い）。 */
export function imageMediaTypeFor(file: { name: string; type: string }): string {
  const mime = (file.type || '').toLowerCase()
  if ((IMAGE_MEDIA_TYPES as readonly string[]).includes(mime)) return mime
  return hasExtension(file.name, ['.jpg', '.jpeg']) ? 'image/jpeg' : 'image/png'
}
