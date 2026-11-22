import { useCallback, useEffect, useRef, useState } from 'react'

import { toErrorMessage } from '../../utils/errors'

type IdentifiableRow = { id: number }
type ListUpdate<TItem> = (items: TItem[]) => TItem[]

/**
 * Settings 系パネル共通: 一覧取得 + id キーの draft マップ同期。
 */
export function useSettingsListWithDrafts<TItem extends IdentifiableRow, TDraft>(options: {
  onError: (e: string | null) => void
  fetchList: () => Promise<TItem[]>
  rowsToDrafts: (rows: readonly TItem[]) => Record<number, TDraft>
}) {
  const { onError, fetchList, rowsToDrafts } = options
  const [list, setList] = useState<TItem[]>([])
  const [drafts, setDrafts] = useState<Record<number, TDraft>>({})

  const load = useCallback(async () => {
    onError(null)
    try {
      const parsed = await fetchList()
      setList(parsed)
      setDrafts(rowsToDrafts(parsed))
    } catch (e) {
      onError(toErrorMessage(e))
    }
  }, [onError, fetchList, rowsToDrafts])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount fetch
    void load()
  }, [load])

  const updateDraft = useCallback((id: number, patch: Partial<TDraft>) => {
    setDrafts((prev) => {
      const base = prev[id]
      if (base === undefined) {
        return prev
      }
      return { ...prev, [id]: { ...base, ...patch } }
    })
  }, [])

  return {
    list,
    setList,
    drafts,
    setDrafts,
    load,
    updateDraft,
  }
}

/**
 * Settings 系パネル共通: 初回 loading 表示付きの一覧取得（draft なし）。
 */
export function useSettingsListFetch<TItem>(options: {
  onError: (msg: string) => void
  fetchList: () => Promise<TItem[]>
}) {
  const { onError, fetchList } = options
  const [list, setList] = useState<TItem[]>([])
  const [loading, setLoading] = useState(true)
  const requests = useRef({ started: 0, applied: 0 })
  const pendingReads = useRef(new Set<ListUpdate<TItem>[]>())

  const updateList = useCallback((update: ListUpdate<TItem>) => {
    // Apply saves to reads already in flight so their other rows can still be used.
    for (const updates of pendingReads.current) updates.push(update)
    setList(update)
  }, [])

  const load = useCallback(async (onSuccess?: () => void) => {
    const request = ++requests.current.started
    const updates: ListUpdate<TItem>[] = []
    pendingReads.current.add(updates)
    try {
      onError('')
      const parsed = await fetchList()
      if (request > requests.current.applied) {
        requests.current.applied = request
        setList(updates.reduce((items, update) => update(items), parsed))
        onSuccess?.()
      }
    } catch (e) {
      if (request > requests.current.applied) onError(toErrorMessage(e))
    } finally {
      pendingReads.current.delete(updates)
      setLoading(false)
    }
  }, [onError, fetchList])

  useEffect(() => {
    void load()
  }, [load])

  return { list, updateList, loading, load }
}
