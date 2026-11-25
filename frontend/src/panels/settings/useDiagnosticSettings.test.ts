import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useDiagnosticSettings } from './useDiagnosticSettings'

it('同じ描画の間に送信が重なっても API を一度だけ呼ぶ', async () => {
  const row = { id: '1', revision: 'original' }
  const api = {
    fetch: vi.fn(async () => ({ items: [row] })),
    save: vi.fn(async (input: { title: string }) => ({ ...row, revision: 'saved', title: input.title })),
    remove: vi.fn(async () => {}),
  }
  const heading = { current: null }
  const { result } = renderHook(() => useDiagnosticSettings(api, heading))
  await waitFor(() => expect(result.current.data?.items).toEqual([row]))
  act(() => result.current.open(row, document.createElement('button')))

  await act(async () => {
    const { save } = result.current
    save({ title: '変更後' })
    save({ title: '変更後' })
  })

  expect(api.save).toHaveBeenCalledOnce()
})
