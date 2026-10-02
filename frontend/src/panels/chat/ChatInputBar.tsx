import { useState, type ClipboardEvent, type DragEvent, type RefObject } from 'react'
import type { ChatSamplePromptRow } from './chatSamplePromptTypes'
import { appendChatSampleTextToDraft } from './appendChatSampleTextToDraft'
import { ChatAttachmentBar } from './ChatAttachmentBar'
import { ChatPreviewSvg, ChatSendSvg } from './chatPanelIcons'
import type {
  ChatAttachmentDraft,
  ChatAttachmentLimits,
} from './attachments/chatAttachmentTypes'

type ChatInputBarProps = {
  loading: boolean
  previewing: boolean
  hasMessages: boolean
  visibleChatSamplePrompts: readonly ChatSamplePromptRow[]
  draft: string
  setDraft: (value: string | ((prev: string) => string)) => void
  draftTextareaRef: RefObject<HTMLTextAreaElement | null>
  onClearConversation: () => void
  onSend: () => void | Promise<void>
  onPreview: () => void | Promise<void>
  /** サーバが WEB 検索可能な構成のときだけトグルを表示する */
  webSearchAvailable: boolean
  enableWebSearch: boolean
  setEnableWebSearch: (value: boolean) => void
  attachments: readonly ChatAttachmentDraft[]
  attachmentLimits: ChatAttachmentLimits
  onAddAttachments: (files: readonly File[]) => void
  onRemoveAttachment: (id: string) => void
}

/** チャットメッセージ入力バー。 */
export function ChatInputBar({
  loading,
  previewing,
  hasMessages,
  visibleChatSamplePrompts,
  draft,
  setDraft,
  draftTextareaRef,
  onClearConversation,
  onSend,
  onPreview,
  webSearchAvailable,
  enableWebSearch,
  setEnableWebSearch,
  attachments,
  attachmentLimits,
  onAddAttachments,
  onRemoveAttachment,
}: ChatInputBarProps) {
  const [dragOver, setDragOver] = useState(false)
  const attachmentsEnabled = attachmentLimits.maxFiles > 0

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return
    const files = Array.from(e.dataTransfer?.files ?? [])
    if (files.length === 0) return
    e.preventDefault()
    setDragOver(false)
    onAddAttachments(files)
  }

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!attachmentsEnabled) return
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
    setDragOver(true)
  }

  /** スクリーンショットを Cmd+V でそのまま添付できるようにする。 */
  const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (!attachmentsEnabled) return
    const files = Array.from(e.clipboardData?.files ?? [])
    if (files.length === 0) return
    e.preventDefault()
    onAddAttachments(files)
  }

  return (
    <div className="chat-panel__composer-stack">
      {webSearchAvailable && (
        <label className="chat-panel__checkbox-label" title="送信するメッセージの応答生成中に、LLM が必要と判断した場合のみ外部の WEB 検索を発行します（固有名・IP は検索クエリに含めません）">
          <input
            type="checkbox"
            checked={enableWebSearch}
            onChange={(e) => setEnableWebSearch(e.target.checked)}
            disabled={loading}
          />
          WEB 検索を許可（このメッセージの応答で外部検索を発行することがあります）
        </label>
      )}
      <button
        type="button"
        className="btn btn--gray"
        disabled={loading || !hasMessages}
        onClick={onClearConversation}
      >
        会話をクリア
      </button>
      <div className="chat-panel__sample-prompts" role="group" aria-label="サンプルの質問">
        {visibleChatSamplePrompts.map((row) => (
          <button
            key={row.id}
            type="button"
            className="btn btn--gray chat-panel__sample-toggle"
            aria-label={`サンプル「${row.label}」`}
            disabled={loading}
            onClick={() => {
              setDraft((d) => appendChatSampleTextToDraft(d, row.text))
            }}
          >
            {row.label}
          </button>
        ))}
      </div>
      <ChatAttachmentBar
        attachments={attachments}
        limits={attachmentLimits}
        loading={loading}
        onAddFiles={onAddAttachments}
        onRemove={onRemoveAttachment}
      />
      <div
        className={`chat-panel__composer${dragOver ? ' chat-panel__composer--dragover' : ''}`}
        onDragOver={onDragOver}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        <div className="chat-panel__composer-field">
          <label className="chat-panel__composer-label">
            メッセージ
            <textarea
              ref={draftTextareaRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.nativeEvent.isComposing) return
                if (e.key !== 'Enter') return
                if (e.shiftKey) {
                  e.preventDefault()
                  setDraft((d) => `${d}\n`)
                  return
                }
                e.preventDefault()
                void onSend()
              }}
              onPaste={onPaste}
              rows={3}
              disabled={loading}
              placeholder="質問を入力…"
            />
          </label>
        </div>
        <button
          type="button"
          className="btn btn--gray chat-panel__icon-btn chat-panel__preview-btn"
          disabled={loading || previewing}
          aria-busy={previewing}
          aria-label={previewing ? 'プレビューを生成中' : 'プレビュー'}
          title={previewing ? 'プレビューを生成中' : 'プレビュー'}
          onClick={() => void onPreview()}
        >
          <ChatPreviewSvg />
        </button>
        <button
          type="button"
          className="btn btn--filled chat-panel__icon-btn chat-panel__send-btn"
          disabled={loading || previewing}
          aria-busy={loading}
          aria-label={loading ? '送信中' : '送信'}
          title={loading ? '送信中' : '送信'}
          onClick={() => void onSend()}
        >
          <ChatSendSvg />
        </button>
      </div>
    </div>
  )
}
