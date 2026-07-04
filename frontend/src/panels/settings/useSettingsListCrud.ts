import { useCallback, useEffect, useState } from 'react'

import { toErrorMessage } from '../../utils/errors'

type IdentifiableRow = { id: number }

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

  const load = useCallback(async () => {
    try {
      onError('')
      const parsed = await fetchList()
      setList(parsed)
    } catch (e) {
      onError(toErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [onError, fetchList])

  useEffect(() => {
    void load()
  }, [load])

  return { list, setList, loading, load }
}
