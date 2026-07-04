import { describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'

import { useSettingsListWithDrafts } from './useSettingsListCrud'

describe('useSettingsListWithDrafts', () => {
  it('load 成功時に list と drafts を同期する', async () => {
    const fetchList = vi.fn(async () => [
      { id: 1, event_type: 'a', score_delta: 10 },
      { id: 2, event_type: 'b', score_delta: 20 },
    ])
    const onError = vi.fn()

    const { result } = renderHook(() =>
      useSettingsListWithDrafts({
        onError,
        fetchList,
        rowsToDrafts: (rows) => Object.fromEntries(rows.map((r) => [r.id, r.score_delta])),
      }),
    )

    await waitFor(() => {
      expect(result.current.list).toHaveLength(2)
    })
    expect(result.current.drafts).toEqual({ 1: 10, 2: 20 })
    expect(onError.mock.calls.every((call) => call[0] === null)).toBe(true)
  })
})
