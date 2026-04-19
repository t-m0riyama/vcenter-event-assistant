import { useEffect, useRef, useState } from 'react'
import type { ChatPreviewResponse } from '../../api/schemas'

function renderWithHighlights(text: string) {
  const regex = /(__LM_[A-Z]+_[0-9]{3}__)/g
  const parts = text.split(regex)
  return parts.map((part, i) => {
    if (regex.test(part)) {
      // mark is used for highlighted text
      return (
        <mark
          key={i}
          className="anonymized-token"
          style={{
            backgroundColor: 'var(--color-primary)',
            color: 'var(--color-on-primary)',
            padding: '2px 4px',
            borderRadius: '4px',
            fontWeight: 'bold',
          }}
        >
          {part}
        </mark>
      )
    }
    return part
  })
}

export function ChatPromptPreviewModal({
  preview,
  onClose,
}: {
  preview: ChatPreviewResponse
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [activeTab, setActiveTab] = useState<'context' | 'history'>('history')

  useEffect(() => {
    // コンポーネントがマウントされたらモーダルを開く
    const el = dialogRef.current
    if (el && !el.open) {
      el.showModal()
    }
  }, [])

  const handleClose = () => {
    const el = dialogRef.current
    if (el) {
      el.close() // これによりネイティブの close イベントが発火する
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog chat-prompt-preview-modal"
      onClose={onClose}
      onCancel={(e) => {
        // ESCキー等でのキャンセル時
        e.preventDefault()
        handleClose()
      }}
    >
      <div className="dialog__header">
        <h2 className="dialog__title">プロンプトプレビュー</h2>
        <button
          type="button"
          className="btn btn--gray dialog__close-btn"
          onClick={handleClose}
          aria-label="閉じる"
        >
          ×
        </button>
      </div>

      <div className="dialog__body">
        {preview.llm_context && (
          <p className="hint" style={{ marginBottom: '1rem' }}>
            LLM コンテキスト（目安）: {preview.llm_context.estimated_input_tokens} / {preview.llm_context.max_input_tokens} トークン
            {preview.llm_context.json_truncated ? '（JSON切り詰めあり）' : '（JSON切り詰めなし）'}
          </p>
        )}

        <nav className="tabs" style={{ marginBottom: '1rem', borderBottom: '1px solid var(--border-color, #e0e0e0)' }}>
          <button
            type="button"
            className={activeTab === 'history' ? 'active' : undefined}
            aria-selected={activeTab === 'history'}
            onClick={() => setActiveTab('history')}
          >
            <span className="tab-button__inner">
              <span className="tab-button__label">送信される会話 ({preview.conversation.length}件)</span>
            </span>
          </button>
          <button
            type="button"
            className={activeTab === 'context' ? 'active' : undefined}
            aria-selected={activeTab === 'context'}
            onClick={() => setActiveTab('context')}
          >
            <span className="tab-button__inner">
              <span className="tab-button__label">バックグラウンドコンテキスト（最新）</span>
            </span>
          </button>
        </nav>

        <div className="chat-prompt-preview-modal__content" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
          {activeTab === 'context' && (
            <pre className="code-block" style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {renderWithHighlights(preview.context_block)}
            </pre>
          )}

          {activeTab === 'history' && (
            <div className="chat-prompt-preview-modal__history">
              {preview.conversation.length === 0 ? (
                <p>会話履歴はありません</p>
              ) : (
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {preview.conversation.map((msg, i) => (
                    <li
                      key={i}
                      style={{
                        marginBottom: '1.25rem',
                        padding: '1rem',
                        background: 'var(--color-background-secondary)',
                        borderRadius: '6px',
                        border: '1px solid var(--color-border)',
                        borderLeft: `4px solid ${msg.role === 'user' ? 'var(--color-primary)' : 'var(--color-text-secondary)'}`,
                      }}
                    >
                      <div style={{ marginBottom: '0.5rem', fontSize: '0.9em', color: 'var(--color-text-secondary)' }}>
                        <strong>{msg.role === 'user' ? '👤 あなた' : '🤖 アシスタント'}</strong>
                      </div>
                      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'inherit' }}>
                        {renderWithHighlights(msg.content)}
                      </pre>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="dialog__footer">
        <button type="button" className="btn btn--filled" onClick={handleClose}>
          閉じる
        </button>
      </div>
    </dialog>
  )
}
