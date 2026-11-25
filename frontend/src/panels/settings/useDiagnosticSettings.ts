import { useEffect, useRef, useState, type RefObject } from 'react'
import { ApiError } from '../../api'
import { errorText } from './setupError'

export const diagnosticProductLabels = { esxi: 'ESXi', vcenter: 'vCenter' }

type Setting = { id: string; revision: string }

export function useDiagnosticSettings<T extends Setting, Input, Data extends { items: T[] }>(api: {
  fetch: (signal?: AbortSignal) => Promise<Data>
  save: (input: Input, row: T | null) => Promise<T>
  remove: (row: T) => Promise<void>
}, heading: RefObject<HTMLHeadingElement | null>, describeError = errorText) {
  const [data, setData] = useState<Data | null>(null)
  const [editor, setEditor] = useState<{ row: T | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [listError, setListError] = useState('')
  const [error, setError] = useState('')
  const [errorCode, setErrorCode] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const [notice, setNotice] = useState('')
  const pending = useRef(false)
  const opener = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void api.fetch(controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result)
    }).catch(e => {
      if (controller.signal.aborted) return
      setListError(errorText(e))
    })
    return () => controller.abort()
  }, [api])

  useEffect(() => {
    if (editor || !opener.current) return
    const button = opener.current
    opener.current = null
    if (button.isConnected && !button.disabled) button.focus()
    if (document.activeElement !== button) heading.current?.focus()
  }, [editor, heading])

  const clearError = () => {
    setError('')
    setErrorCode(null)
  }

  const open = (row: T | null, button: HTMLButtonElement) => {
    opener.current = button
    clearError()
    setNotice('')
    setEditor({ row })
  }

  const close = () => {
    clearError()
    setEditor(null)
  }

  const run = async (work: () => Promise<void>, checkRevision = false) => {
    // React が disabled を反映する前の連続した送信も防ぐ。
    if (pending.current) return
    pending.current = true
    setBusy(true)
    clearError()
    setNotice('')
    try {
      await work()
    } catch (e) {
      setErrorCode(e instanceof ApiError ? e.errorCode : null)
      if (checkRevision && e instanceof ApiError
        && (e.status === 404 || (e.status === 409 && e.errorCode === 'diagnostic_setting_stale'))) {
        setConflict(true)
        setError(e.status === 404 ? 'この設定は削除されました。' : describeError(e))
      } else {
        setError(describeError(e))
      }
    } finally {
      pending.current = false
      setBusy(false)
    }
  }

  const fetchList = async () => {
    setListError('')
    try {
      const fresh = await api.fetch()
      setData(fresh)
      return fresh
    } catch (e) {
      setListError(errorText(e))
      return null
    }
  }

  const reload = () => run(async () => {
    if (await fetchList()) {
      setConflict(false)
      close()
    }
  })

  const save = (input: Input) => {
    if (!editor || conflict) return
    const { row } = editor
    void run(async () => {
      const saved = await api.save(input, row)
      setData(current => current && {
        ...current,
        items: row ? current.items.map(item => item.id === saved.id ? saved : item) : [...current.items, saved],
      })
      // 名前順はサーバーの並びに合わせる。再取得に失敗しても保存済みの行は残す。
      await fetchList()
      close()
      setNotice('保存しました。')
    }, row !== null)
  }

  const remove = () => {
    const row = editor?.row
    if (!row || pending.current || conflict || !confirm('この設定を削除しますか？')) return
    void run(async () => {
      await api.remove(row)
      setData(current => current && { ...current, items: current.items.filter(item => item.id !== row.id) })
      close()
      setNotice('削除しました。')
    }, true)
  }

  return { data, editor, busy, listError, error, errorCode, conflict, notice, open, close, clearError, fetchList, reload, save, remove }
}
