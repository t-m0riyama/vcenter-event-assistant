import { useCallback, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import { apiPatch } from '../api'
import type { EventRow } from '../api/schemas'
import { eventRowSchema } from '../api/schemas'
import { toErrorMessage } from '../utils/errors'

export type UseEventCommentEditConfig = {
  onError: (msg: string | null) => void
  setRows?: Dispatch<SetStateAction<EventRow[]>>
  /** テスト差し替え用。未指定時は apiPatch を使用。 */
  patchComment?: (eventId: number, commentDraft: string) => Promise<EventRow>
}

/**
 * イベント一覧の運用メモ（user_comment）編集状態と保存処理。
 */
export function useEventCommentEdit(config: UseEventCommentEditConfig) {
  const { onError, setRows, patchComment = defaultPatchComment } = config
  const [editingCommentId, setEditingCommentId] = useState<number | null>(null)
  const [commentDraft, setCommentDraft] = useState('')

  const beginCommentEdit = useCallback((event: EventRow) => {
    setEditingCommentId(event.id)
    setCommentDraft(event.user_comment ?? '')
  }, [])

  const cancelCommentEdit = useCallback(() => {
    setEditingCommentId(null)
    setCommentDraft('')
  }, [])

  const resetCommentEdit = useCallback(() => {
    setEditingCommentId(null)
    setCommentDraft('')
  }, [])

  const saveComment = useCallback(
    async (eventId: number) => {
      onError(null)
      try {
        const updated = await patchComment(eventId, commentDraft)
        if (setRows) {
          setRows((prev) => prev.map((r) => (r.id === eventId ? { ...r, ...updated } : r)))
        }
        resetCommentEdit()
      } catch (e) {
        onError(toErrorMessage(e))
      }
    },
    [commentDraft, onError, patchComment, resetCommentEdit, setRows],
  )

  return {
    editingCommentId,
    commentDraft,
    setCommentDraft,
    beginCommentEdit,
    cancelCommentEdit,
    resetCommentEdit,
    saveComment,
  }
}

async function defaultPatchComment(eventId: number, commentDraft: string): Promise<EventRow> {
  const raw = await apiPatch<unknown>(`/api/events/${eventId}`, {
    user_comment: commentDraft.trim() === '' ? null : commentDraft,
  })
  return eventRowSchema.parse(raw)
}
