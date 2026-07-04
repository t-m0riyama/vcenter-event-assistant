/**
 * @vitest-environment happy-dom
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { EventRow } from '../api/schemas'
import { useEventCommentEdit } from './useEventCommentEdit'

const row: EventRow = {
  id: 42,
  vcenter_id: 'vc-1',
  occurred_at: '2026-03-22T10:00:00Z',
  event_type: 'VmPoweredOnEvent',
  message: 'm',
  severity: 'info',
  user_name: null,
  entity_name: null,
  entity_type: null,
  notable_score: 1,
  notable_tags: null,
  user_comment: 'old',
  type_guide: null,
}

describe('useEventCommentEdit', () => {
  it('beginCommentEdit で draft を初期化する', () => {
    const { result } = renderHook(() =>
      useEventCommentEdit({ onError: vi.fn(), patchComment: vi.fn() }),
    )
    act(() => {
      result.current.beginCommentEdit(row)
    })
    expect(result.current.editingCommentId).toBe(42)
    expect(result.current.commentDraft).toBe('old')
  })

  it('saveComment 成功後に編集状態をクリアし rows を更新する', async () => {
    const patchComment = vi.fn().mockResolvedValue({ ...row, user_comment: 'new' })
    const setRows = vi.fn()
    const { result } = renderHook(() =>
      useEventCommentEdit({ onError: vi.fn(), patchComment, setRows }),
    )
    act(() => {
      result.current.beginCommentEdit(row)
      result.current.setCommentDraft('new')
    })
    await act(async () => {
      await result.current.saveComment(42)
    })
    expect(patchComment).toHaveBeenCalledWith(42, 'new')
    expect(setRows).toHaveBeenCalled()
    expect(result.current.editingCommentId).toBeNull()
    expect(result.current.commentDraft).toBe('')
  })
})
