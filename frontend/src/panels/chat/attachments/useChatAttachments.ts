import { useCallback, useState } from 'react'

import { randomId } from '../../../utils/randomId'
import { toErrorMessage } from '../../../utils/errors'
import { buildChatAttachmentPayloads } from './buildChatAttachmentPayloads'
import { chatAttachmentRejectionReason } from './chatAttachmentRejection'
import { classifyChatAttachmentFile } from './classifyChatAttachmentFile'
import { downscaleImageAttachment } from './downscaleImageAttachment'
import { readTextAttachment } from './readTextAttachment'
import type {
  ChatAttachmentDraft,
  ChatAttachmentLimits,
  ChatAttachmentPayload,
} from './chatAttachmentTypes'

/**
 * 入力欄の添付一覧を管理する。
 *
 * 添付は送信したターン限りの入力なので、`sessionStorage` には保存しない
 * （会話履歴と違い再送もしない。画像 base64 で保存領域を潰さない狙いもある）。
 */
export function useChatAttachments(limits: ChatAttachmentLimits) {
  const [attachments, setAttachments] = useState<ChatAttachmentDraft[]>([])

  const updateDraft = useCallback((id: string, patch: Partial<ChatAttachmentDraft>) => {
    setAttachments((prev) => prev.map((d) => (d.id === id ? { ...d, ...patch } : d)))
  }, [])

  const addFiles = useCallback(
    (files: readonly File[]) => {
      if (files.length === 0) return
      // 判定は setState の updater ではなくここで行う。
      // updater は React が後で実行するため、その中で読み取りを起動すると走らない。
      const drafts: ChatAttachmentDraft[] = []
      const accepted: { draft: ChatAttachmentDraft; file: File }[] = []
      let acceptedCount = attachments.filter((d) => d.status !== 'error').length

      for (const file of files) {
        const kind = classifyChatAttachmentFile(file)
        const reason = chatAttachmentRejectionReason(file, kind, limits, acceptedCount)
        const draft: ChatAttachmentDraft = {
          id: randomId(),
          filename: file.name,
          sizeBytes: file.size,
          kind,
          status: reason ? 'error' : 'reading',
          error: reason ?? undefined,
        }
        drafts.push(draft)
        if (!reason) {
          accepted.push({ draft, file })
          acceptedCount += 1
        }
      }
      setAttachments((prev) => [...prev, ...drafts])

      for (const { draft, file } of accepted) {
        void (async () => {
          try {
            const payload: ChatAttachmentPayload =
              draft.kind === 'image'
                ? await downscaleImageAttachment(file)
                : await readTextAttachment(file, limits.maxTextChars)
            updateDraft(draft.id, {
              status: 'ready',
              payload,
              previewUrl:
                payload.kind === 'image'
                  ? `data:${payload.media_type};base64,${payload.data_base64}`
                  : undefined,
            })
          } catch (e) {
            updateDraft(draft.id, { status: 'error', error: toErrorMessage(e) })
          }
        })()
      }
    },
    [attachments, limits, updateDraft],
  )

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((d) => d.id !== id))
  }, [])

  const clearAttachments = useCallback(() => {
    setAttachments([])
  }, [])

  /** 送信失敗時に、クリアした添付を入力欄へ戻す。 */
  const restoreAttachments = useCallback((drafts: readonly ChatAttachmentDraft[]) => {
    setAttachments([...drafts])
  }, [])

  const attachmentPayloads = useCallback(
    () => buildChatAttachmentPayloads(attachments),
    [attachments],
  )

  return {
    attachments,
    addFiles,
    removeAttachment,
    clearAttachments,
    restoreAttachments,
    attachmentPayloads,
  }
}
