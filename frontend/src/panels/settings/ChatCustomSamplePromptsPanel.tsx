/**
 * チャットのカスタムサンプル質問を追加・編集・削除する設定パネル。
 */
import { useCallback } from 'react'

import type { ChatSamplePromptRow } from '../chat/chatSamplePromptTypes'
import { useChatCustomSamplePrompts } from '../../preferences/useChatCustomSamplePrompts'

export function ChatCustomSamplePromptsPanel() {
  const { customSamplePrompts, setCustomSamplePrompts } = useChatCustomSamplePrompts()

  const addRow = useCallback(() => {
    const row: ChatSamplePromptRow = {
      id: crypto.randomUUID(),
      label: '新しいサンプル',
      text: 'ここに質問文を入力してください。',
    }
    setCustomSamplePrompts([...customSamplePrompts, row])
  }, [customSamplePrompts, setCustomSamplePrompts])

  const updateRow = useCallback(
    (id: string, patch: Partial<Pick<ChatSamplePromptRow, 'label' | 'text'>>) => {
      setCustomSamplePrompts(
        customSamplePrompts.map((r) => (r.id === id ? { ...r, ...patch } : r)),
      )
    },
    [customSamplePrompts, setCustomSamplePrompts],
  )

  const removeRow = useCallback(
    (id: string) => {
      setCustomSamplePrompts(customSamplePrompts.filter((r) => r.id !== id))
    },
    [customSamplePrompts, setCustomSamplePrompts],
  )

  return (
    <div className="panel">
      <h2>チャットサンプル</h2>
      <p className="hint">
        チャットタブに表示する「サンプルの質問」のうち、ここで追加した行が既定サンプルの後に並びます。保存先はこのブラウザの
        localStorage です。
      </p>
      <p className="hint">
        ラベルと本文の両方に文字が入っている行だけがチャットのチップに表示されます。
      </p>
      <div className="chat-custom-samples-actions">
        <button type="button" className="btn btn--gray" onClick={addRow}>
          サンプルを追加
        </button>
      </div>
      <ul className="chat-custom-samples-list">
        {customSamplePrompts.map((row) => (
          <li key={row.id} className="chat-custom-samples-row">
            <label className="chat-custom-samples-field">
              表示ラベル
              <input
                type="text"
                value={row.label}
                onChange={(e) => {
                  updateRow(row.id, { label: e.target.value })
                }}
                aria-label={`カスタムサンプル ${row.id} の表示ラベル`}
              />
            </label>
            <label className="chat-custom-samples-field">
              質問本文
              <textarea
                value={row.text}
                rows={3}
                onChange={(e) => {
                  updateRow(row.id, { text: e.target.value })
                }}
                aria-label={`カスタムサンプル ${row.id} の質問本文`}
              />
            </label>
            <button
              type="button"
              className="btn btn--gray"
              onClick={() => {
                removeRow(row.id)
              }}
            >
              削除
            </button>
          </li>
        ))}
      </ul>
      {customSamplePrompts.length === 0 && (
        <p className="hint">カスタムサンプルはまだありません。「サンプルを追加」で作成できます。</p>
      )}
    </div>
  )
}
