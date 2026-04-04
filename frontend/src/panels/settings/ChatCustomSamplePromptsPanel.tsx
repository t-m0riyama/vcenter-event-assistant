/**
 * チャットのサンプル質問を追加・編集・削除し、JSON でエクスポート・インポートする設定パネル。
 */
import { useCallback, useRef, useState } from 'react'

import type { ChatSamplePromptRow } from '../chat/chatSamplePromptTypes'
import { downloadJsonFile } from '../../utils/downloadJsonFile'
import { toErrorMessage } from '../../utils/errors'
import { useChatCustomSamplePrompts } from '../../preferences/useChatCustomSamplePrompts'
import {
  buildChatSamplePromptsExportPayload,
  chatSamplePromptsFileSchema,
  mergeChatSamplePromptsImport,
  type ChatSamplePromptsFile,
} from './chatSamplePromptsFile'
import { formatChatSamplePromptsFileParseError } from './chatSamplePromptsImportErrors'

function confirmDestructiveChatSampleImport(deleteNotInImport: boolean, sampleCount: number): boolean {
  if (!deleteNotInImport) return true
  if (sampleCount === 0) {
    return confirm(
      'このファイルにはサンプルが含まれていません。オプションに従い既存のサンプルがすべて削除される可能性があります。よろしいですか？',
    )
  }
  return confirm('ファイルに含まれない id のサンプルは削除されます。よろしいですか？')
}

export function ChatCustomSamplePromptsPanel({ onError }: { onError: (e: string | null) => void }) {
  const { chatSamplePrompts, setChatSamplePrompts } = useChatCustomSamplePrompts()
  const [overwriteExisting, setOverwriteExisting] = useState(true)
  const [deleteSamplesNotInImport, setDeleteSamplesNotInImport] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addRow = useCallback(() => {
    const row: ChatSamplePromptRow = {
      id: crypto.randomUUID(),
      label: '新しいサンプル',
      text: 'ここに質問文を入力してください。',
    }
    setChatSamplePrompts([...chatSamplePrompts, row])
  }, [chatSamplePrompts, setChatSamplePrompts])

  const updateRow = useCallback(
    (id: string, patch: Partial<Pick<ChatSamplePromptRow, 'label' | 'text'>>) => {
      setChatSamplePrompts(
        chatSamplePrompts.map((r) => (r.id === id ? { ...r, ...patch } : r)),
      )
    },
    [chatSamplePrompts, setChatSamplePrompts],
  )

  const removeRow = useCallback(
    (id: string) => {
      setChatSamplePrompts(chatSamplePrompts.filter((r) => r.id !== id))
    },
    [chatSamplePrompts, setChatSamplePrompts],
  )

  const exportToFile = () => {
    onError(null)
    try {
      const payload = buildChatSamplePromptsExportPayload(chatSamplePrompts)
      const name = `vea-chat-sample-prompts-${new Date().toISOString().slice(0, 10)}.json`
      downloadJsonFile(name, payload)
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }

  const onImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return

    let parsedFile: ChatSamplePromptsFile
    try {
      const text = await file.text()
      const json: unknown = JSON.parse(text)
      parsedFile = chatSamplePromptsFileSchema.parse(json)
    } catch (err) {
      onError(formatChatSamplePromptsFileParseError(err))
      return
    }

    if (!confirmDestructiveChatSampleImport(deleteSamplesNotInImport, parsedFile.samples.length)) {
      return
    }

    onError(null)
    try {
      const merged = mergeChatSamplePromptsImport(chatSamplePrompts, parsedFile.samples, {
        overwriteExisting,
        deleteNotInImport: deleteSamplesNotInImport,
      })
      setChatSamplePrompts(merged)
    } catch (err) {
      onError(toErrorMessage(err))
    }
  }

  return (
    <div className="panel">
      <h2>チャットサンプル</h2>
      <p className="hint">
        チャットタブの「サンプルの質問」チップに並ぶ行を編集します。保存先はこのブラウザの
        localStorage です。既定の行もここから編集・削除できます。
      </p>
      <p className="hint">
        ラベルと本文の両方に文字が入っている行だけがチャットのチップに表示されます。
      </p>

      <h2>エクスポート・インポート</h2>
      <p className="hint">
        サンプル一覧を JSON でエクスポート・インポートできます。下の「インポート時のオプション」は「ファイルからインポート」にのみ効きます。
      </p>
      <fieldset className="score-rules-import-options">
        <legend className="score-rules-import-options__legend">インポート時のオプション</legend>
        <div className="form-grid score-rules-form score-rules-import-options__grid">
          <label className="check">
            <input
              type="checkbox"
              checked={overwriteExisting}
              onChange={(ev) => setOverwriteExisting(ev.target.checked)}
              aria-label="既存の同一 id を上書き"
            />
            既存の同一 id を上書き
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={deleteSamplesNotInImport}
              onChange={(ev) => setDeleteSamplesNotInImport(ev.target.checked)}
              aria-label="ファイルに含まれない id のサンプルを削除"
            />
            ファイルに含まれない id のサンプルを削除
          </label>
        </div>
      </fieldset>
      <div className="score-rules-file-actions">
        <button type="button" className="btn btn--gray" onClick={exportToFile}>
          ファイルにエクスポート
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden-file-input"
          aria-label="チャットサンプル JSON を選択"
          onChange={(ev) => void onImportFileChange(ev)}
        />
        <button
          type="button"
          className="btn btn--filled"
          onClick={() => fileInputRef.current?.click()}
        >
          ファイルからインポート
        </button>
      </div>

      <h2>一覧</h2>
      <div className="chat-custom-samples-actions">
        <button type="button" className="btn btn--gray" onClick={addRow}>
          サンプルを追加
        </button>
      </div>
      <ul className="chat-custom-samples-list">
        {chatSamplePrompts.map((row) => (
          <li key={row.id} className="chat-custom-samples-row">
            <label className="chat-custom-samples-field">
              表示ラベル
              <input
                type="text"
                value={row.label}
                onChange={(e) => {
                  updateRow(row.id, { label: e.target.value })
                }}
                aria-label={`サンプル ${row.id} の表示ラベル`}
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
                aria-label={`サンプル ${row.id} の質問本文`}
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
      {chatSamplePrompts.length === 0 && (
        <p className="hint">サンプルがありません。「サンプルを追加」で作成できます。</p>
      )}
    </div>
  )
}
