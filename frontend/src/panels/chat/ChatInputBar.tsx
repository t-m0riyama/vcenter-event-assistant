import type { RefObject } from 'react'
import type { ChatSamplePromptRow } from './chatSamplePromptTypes'
import { appendChatSampleTextToDraft } from './appendChatSampleTextToDraft'
import { ChatPreviewSvg, ChatSendSvg } from './chatPanelIcons'

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
}: ChatInputBarProps) {
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
      <div className="chat-panel__composer">
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
