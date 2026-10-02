import { useRef, type ChangeEvent } from 'react'

import { ChatAttachSvg, ChatRemoveSvg } from './chatPanelIcons'
import { CHAT_ATTACHMENT_ACCEPT } from './attachments/classifyChatAttachmentFile'
import { formatAttachmentSize } from './attachments/chatAttachmentRejection'
import type {
  ChatAttachmentDraft,
  ChatAttachmentLimits,
} from './attachments/chatAttachmentTypes'

type ChatAttachmentBarProps = {
  attachments: readonly ChatAttachmentDraft[]
  limits: ChatAttachmentLimits
  loading: boolean
  onAddFiles: (files: readonly File[]) => void
  onRemove: (id: string) => void
}

/**
 * 入力欄の添付ファイル一覧と追加ボタン。
 *
 * 添付は送信したターンにのみ付き、サーバにも会話履歴にも保存されない。
 * 画像は匿名化の対象外なので、1 枚でも添付されたらその旨を明示する。
 */
export function ChatAttachmentBar({
  attachments,
  limits,
  loading,
  onAddFiles,
  onRemove,
}: ChatAttachmentBarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  if (limits.maxFiles <= 0) {
    return null
  }

  const onFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    onAddFiles(Array.from(e.target.files ?? []))
    // 同じファイルを続けて選び直せるようにする
    e.target.value = ''
  }

  const hasImage = attachments.some((a) => a.kind === 'image' && a.status !== 'error')
  const full = attachments.filter((a) => a.status !== 'error').length >= limits.maxFiles

  return (
    <div className="chat-panel__attachments">
      <div className="chat-panel__attachment-actions">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={CHAT_ATTACHMENT_ACCEPT}
          className="chat-panel__attachment-input"
          onChange={onFileInputChange}
        />
        <button
          type="button"
          className="btn btn--gray chat-panel__attachment-add"
          disabled={loading || full}
          onClick={() => fileInputRef.current?.click()}
        >
          <ChatAttachSvg />
          ファイルを添付
        </button>
        <span className="hint chat-panel__attachment-limits">
          ログ・CSV・JSON などのテキストと PNG / JPEG 画像を {limits.maxFiles} 件・各{' '}
          {formatAttachmentSize(limits.maxFileBytes)} まで。ドラッグ&amp;ドロップと貼り付けも使えます。
          添付はこの質問にのみ付き、サーバーには保存しません。
        </span>
      </div>

      {attachments.length > 0 && (
        <ul className="chat-panel__attachment-list" aria-label="添付ファイル">
          {attachments.map((a) => (
            <li
              key={a.id}
              className={`chat-panel__attachment-chip chat-panel__attachment-chip--${a.status}`}
            >
              {a.previewUrl ? (
                <img className="chat-panel__attachment-thumb" src={a.previewUrl} alt="" />
              ) : null}
              <span className="chat-panel__attachment-name" title={a.filename}>
                {a.filename}
              </span>
              <span className="chat-panel__attachment-meta">
                {a.status === 'reading' && '読み取り中…'}
                {a.status === 'ready' && formatAttachmentSize(a.sizeBytes)}
                {a.status === 'error' && a.error}
                {a.status === 'ready' && a.payload?.truncated && '・長いため末尾を省略'}
              </span>
              <button
                type="button"
                className="btn btn--gray chat-panel__icon-btn chat-panel__attachment-remove"
                aria-label={`添付「${a.filename}」を外す`}
                title="添付を外す"
                disabled={loading}
                onClick={() => onRemove(a.id)}
              >
                <ChatRemoveSvg />
              </button>
            </li>
          ))}
        </ul>
      )}

      {hasImage && (
        <p className="hint chat-panel__attachment-warning" role="status" aria-live="polite">
          画像は匿名化されず、そのまま LLM に送信されます。ホスト名・IP
          アドレス・アカウント名の写り込みにご注意ください。
        </p>
      )}
    </div>
  )
}
