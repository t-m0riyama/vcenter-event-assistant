import { describe, expect, it } from 'vitest'

import {
  buildChatSamplePromptsExportPayload,
  chatSamplePromptsFileSchema,
  mergeChatSamplePromptsImport,
} from './chatSamplePromptsFile'

describe('chatSamplePromptsFile', () => {
  it('buildChatSamplePromptsExportPayload がスキーマ通りのオブジェクトを返す', () => {
    const rows = [{ id: 'a', label: 'L', text: 'T' }]
    const payload = buildChatSamplePromptsExportPayload(rows)
    expect(chatSamplePromptsFileSchema.parse(payload)).toEqual(payload)
    expect(payload.format).toBe('vea-chat-sample-prompts')
    expect(payload.samples).toEqual(rows)
  })

  it('merge: 上書きオフは既存 id を保持し、新規 id のみ追加', () => {
    const current = [
      { id: 'a', label: 'old', text: '1' },
      { id: 'b', label: 'B', text: '2' },
    ]
    const file = [
      { id: 'a', label: 'new', text: '9' },
      { id: 'c', label: 'C', text: '3' },
    ]
    const out = mergeChatSamplePromptsImport(current, file, {
      overwriteExisting: false,
      deleteNotInImport: false,
    })
    expect(out.find((r) => r.id === 'a')).toEqual(current[0])
    expect(out.some((r) => r.id === 'c')).toBe(true)
  })

  it('merge: 上書きオンはファイルの内容で既存 id を置換', () => {
    const current = [{ id: 'a', label: 'old', text: '1' }]
    const file = [{ id: 'a', label: 'new', text: '9' }]
    const out = mergeChatSamplePromptsImport(current, file, {
      overwriteExisting: true,
      deleteNotInImport: false,
    })
    expect(out).toEqual(file)
  })

  it('merge: ファイルに無い id は deleteNotInImport で削除', () => {
    const current = [
      { id: 'a', label: 'A', text: '1' },
      { id: 'b', label: 'B', text: '2' },
    ]
    const file = [{ id: 'a', label: 'A2', text: '1' }]
    const out = mergeChatSamplePromptsImport(current, file, {
      overwriteExisting: true,
      deleteNotInImport: true,
    })
    expect(out.map((r) => r.id)).toEqual(['a'])
  })

  it('merge: 順序はファイルの id 初出順、その後に残りの既存', () => {
    const current = [
      { id: 'x', label: 'X', text: 'x' },
      { id: 'y', label: 'Y', text: 'y' },
    ]
    const file = [{ id: 'y', label: 'Y2', text: 'y2' }]
    const out = mergeChatSamplePromptsImport(current, file, {
      overwriteExisting: true,
      deleteNotInImport: false,
    })
    expect(out.map((r) => r.id)).toEqual(['y', 'x'])
  })
})
