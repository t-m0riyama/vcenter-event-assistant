import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { apiGet } from '../api'
import {
  postIncidentTimelineView,
  TimelineBusyError,
  TimelineRequestSupersededError,
} from '../api/incidentTimelineView'
import type { IncidentTimelineViewResponse, VCenter } from '../api/schemas'
import { parseApiUtcInstantMs } from '../datetime/formatIsoInTimeZone'
import { resolveEventApiRange } from '../datetime/graphRange'
import { useTimeZone } from '../datetime/useTimeZone'
import {
  zonedRangePartsFromUtcIsoEndpoints,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../datetime/zonedRangeParts'
import {
  buildViewRequest,
  resolveTimelineRange,
  validateResolvedRange,
  widenRange,
  type ResolvedRange,
  type TimelineSortOrder,
} from '../panels/timeline/timelineModel'
import { parseAppHash } from '../routing/appHashRouting'
import {
  buildTimelineHash,
  DEFAULT_TIMELINE_CONDITIONS,
  readTimelineHash,
  replaceTimelineHash,
  TIMELINE_SOURCE_KINDS,
  type TimelineConditions,
  type TimelineRange,
  type TimelineSourceKind,
} from '../routing/timelineHash'
import { asArray } from '../utils/asArray'
import { toErrorMessage } from '../utils/errors'

/** 並び順の保存先（旧タイムラインから引き継ぐ）。 */
export const TIMELINE_SORT_ORDER_STORAGE_KEY = 'vea.timeline.sort_order'
/** 対象の検索欄の入力が止まってから API を呼ぶまでの待ち時間（ミリ秒）。 */
export const TIMELINE_ENTITY_DEBOUNCE_MS = 400

/** `invalid` は期間などの入力の誤り、`busy` は混み合い、`error` はそれ以外。 */
export type TimelineLoadError = { readonly kind: 'invalid' | 'busy' | 'error'; readonly message: string }

type Job = { readonly id: number; readonly body: ReturnType<typeof buildViewRequest> | null }

function readSortOrder(): TimelineSortOrder {
  try {
    return localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY) === 'asc' ? 'asc' : 'desc'
  } catch {
    return 'desc'
  }
}

function toLoadError(e: unknown): TimelineLoadError {
  if (e instanceof TimelineBusyError) return { kind: 'busy', message: e.message }
  // 422 は ApiError がサーバの detail をそのまま message にしている
  return { kind: 'error', message: toErrorMessage(e) }
}

/**
 * タイムラインタブの条件・URL・読み込みをまとめる。
 *
 * - 条件の正本は UTC の {@link TimelineConditions}。URL のハッシュと一致させる（履歴は replace）。
 * - タブが表示中（`active`）のときだけ URL を書く。パネルは非表示でもマウントされたままで、
 *   別のタブの URL を奪わないため。
 * - 条件が変わると自動で読み込む。サーバは利用者ごとの同時実行数が 1 で、重ねると 503 になるので、
 *   送信中は 1 本だけにし、その間に条件が変わったら最新の条件を 1 つだけ保留して、終わってから送る。
 *   古い要求の応答は捨てる。
 */
export function useTimelineViewController(
  onError: (e: string | null) => void,
  { active = true }: { active?: boolean } = {},
) {
  const { timeZone } = useTimeZone()
  const [conditions, setConditions] = useState<TimelineConditions>(
    () => readTimelineHash() ?? DEFAULT_TIMELINE_CONDITIONS,
  )
  const [entityInput, setEntityInput] = useState(conditions.entity)
  const [rangeHistory, setRangeHistory] = useState<readonly TimelineRange[]>([])
  const [reloadNonce, setReloadNonce] = useState(0)
  const [resolvedRange, setResolvedRange] = useState<ResolvedRange>(() =>
    resolveTimelineRange(conditions.range, Date.now()),
  )
  const [data, setData] = useState<IncidentTimelineViewResponse | null>(null)
  /** `data` を取得したときの期間（保存・スナップショットに使う。応答の時刻表記には頼らない）。 */
  const [loadedRange, setLoadedRange] = useState<ResolvedRange | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<TimelineLoadError | null>(null)
  const [sortOrder, setSortOrderState] = useState<TimelineSortOrder>(readSortOrder)
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [rangeDraft, setRangeDraft] = useState<{ key: string; parts: ZonedRangeParts } | null>(null)
  const [rangeInputError, setRangeInputError] = useState<string | null>(null)

  const conditionsRef = useRef(conditions)
  conditionsRef.current = conditions
  const activeRef = useRef(active)
  activeRef.current = active

  // ---- 並び順・vCenter 一覧 -------------------------------------------------
  const setSortOrder = useCallback((next: TimelineSortOrder) => {
    setSortOrderState(next)
    try {
      localStorage.setItem(TIMELINE_SORT_ORDER_STORAGE_KEY, next)
    } catch {
      // 保存できなくても表示は変えられる
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    apiGet<unknown>('/api/vcenters')
      .then((raw) => {
        if (!cancelled) setVcenters(asArray<VCenter>(raw))
      })
      .catch((e) => {
        if (!cancelled) onError(toErrorMessage(e))
      })
    return () => {
      cancelled = true
    }
  }, [onError])

  // ---- 対象の検索欄: 入力が止まってから条件に反映する ---------------------------
  useEffect(() => {
    const next = entityInput.trim()
    if (next === conditions.entity) return
    const timer = setTimeout(() => {
      setConditions((c) => ({ ...c, entity: next }))
    }, TIMELINE_ENTITY_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [entityInput, conditions.entity])

  // ---- 読み込み（1 本ずつ・最新の条件だけ） ------------------------------------
  const jobCounterRef = useRef(0)
  const desiredRef = useRef<Job | null>(null)
  const sentIdRef = useRef(0)
  const runningRef = useRef(false)
  const mountedRef = useRef(true)
  const lastKeyRef = useRef<string | null>(null)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const pump = useCallback(async () => {
    if (runningRef.current) return
    runningRef.current = true
    try {
      while (desiredRef.current && desiredRef.current.id !== sentIdRef.current) {
        const job = desiredRef.current
        sentIdRef.current = job.id
        if (!job.body) continue
        const isCurrent = () => desiredRef.current?.id === job.id && mountedRef.current
        try {
          const res = await postIncidentTimelineView(job.body, () => !isCurrent())
          if (isCurrent()) {
            setData(res)
            setLoadedRange({ from: job.body.from, to: job.body.to })
            setError(null)
          }
        } catch (e) {
          if (e instanceof TimelineRequestSupersededError) continue
          if (isCurrent()) {
            setData(null)
            setLoadedRange(null)
            setError(toLoadError(e))
          }
        }
      }
    } finally {
      runningRef.current = false
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  const loadKey = useMemo(() => JSON.stringify({ conditions, reloadNonce }), [conditions, reloadNonce])

  useEffect(() => {
    if (!active) return
    // StrictMode の二重実行や、同じ条件での再実行で同じ要求を重ねない（更新ボタンは reloadNonce で変わる）
    if (lastKeyRef.current === loadKey) return
    lastKeyRef.current = loadKey
    const range = resolveTimelineRange(conditionsRef.current.range, Date.now())
    setResolvedRange(range)
    const invalid = validateResolvedRange(range)
    if (invalid) {
      desiredRef.current = { id: ++jobCounterRef.current, body: null }
      setData(null)
      setLoadedRange(null)
      setError({ kind: 'invalid', message: invalid })
      void pump()
      return
    }
    desiredRef.current = {
      id: ++jobCounterRef.current,
      body: buildViewRequest(conditionsRef.current, range),
    }
    setLoading(true)
    void pump()
  }, [active, loadKey, pump])

  // ---- URL との同期 -----------------------------------------------------------
  const isTimelineHash = () => parseAppHash(window.location.hash).tab === 'timeline'

  useEffect(() => {
    if (active && isTimelineHash()) replaceTimelineHash(conditions)
  }, [active, conditions])

  const adoptFromLocation = useCallback(() => {
    if (!isTimelineHash()) return
    const incoming = readTimelineHash()
    if (!incoming) {
      // タブ切り替えで `#/timeline` に戻った。持っている条件を URL に書き直す
      replaceTimelineHash(conditionsRef.current)
      return
    }
    if (buildTimelineHash(incoming) !== buildTimelineHash(conditionsRef.current)) {
      setConditions(incoming)
      setEntityInput(incoming.entity)
      setRangeHistory([])
    }
  }, [])

  useEffect(() => {
    window.addEventListener('hashchange', adoptFromLocation)
    return () => window.removeEventListener('hashchange', adoptFromLocation)
  }, [adoptFromLocation])

  // 別のタブから戻ったとき: URL（他タブからの入口リンク）を取り込み、直近 N 時間なら読み直す
  const wasActiveRef = useRef(active)
  useEffect(() => {
    if (active && !wasActiveRef.current) {
      adoptFromLocation()
      setReloadNonce((n) => n + 1)
    }
    wasActiveRef.current = active
  }, [active, adoptFromLocation])

  // ---- 条件の変更 -------------------------------------------------------------
  const patch = useCallback((next: Partial<TimelineConditions>) => {
    setConditions((c) => ({ ...c, ...next }))
  }, [])

  const setRange = useCallback((range: TimelineRange, keepHistory: boolean) => {
    if (!keepHistory) setRangeHistory([])
    setConditions((c) => ({ ...c, range }))
  }, [])

  const selectRollingPreset = useCallback(
    (durationMs: number) => {
      setRangeInputError(null)
      setRange({ mode: 'rolling', durationMs }, false)
    },
    [setRange],
  )

  /** 期間を固定する（起点の前後のプリセット、スナップショットなど）。履歴は消す。 */
  const setFixedRange = useCallback(
    (range: ResolvedRange) => {
      setRangeInputError(null)
      setRange({ mode: 'fixed', from: range.from, to: range.to }, false)
    },
    [setRange],
  )

  /** 俯瞰グラフから期間を絞る。絞る前の期間を覚えて、{@link undoZoom} で戻せる。 */
  const zoomTo = useCallback((range: ResolvedRange) => {
    setRangeInputError(null)
    setRangeHistory((h) => [...h, conditionsRef.current.range])
    setConditions((c) => ({ ...c, range: { mode: 'fixed', from: range.from, to: range.to } }))
  }, [])

  const undoZoom = useCallback(() => {
    const previous = rangeHistory[rangeHistory.length - 1]
    if (!previous) return
    setRangeHistory((h) => h.slice(0, -1))
    setConditions((c) => ({ ...c, range: previous }))
  }, [rangeHistory])

  const widen = useCallback(() => {
    const current = resolveTimelineRange(conditionsRef.current.range, Date.now())
    setFixedRange(widenRange(current, conditionsRef.current.range))
  }, [setFixedRange])

  const rangeKey = JSON.stringify(conditions.range)
  const derivedParts = useMemo(
    () => zonedRangePartsFromUtcIsoEndpoints(resolvedRange.from, resolvedRange.to, timeZone),
    [resolvedRange, timeZone],
  )
  const rangeParts = rangeDraft && rangeDraft.key === rangeKey ? rangeDraft.parts : derivedParts

  /** 期間の入力欄の編集。開始・終了がそろって有効になったら固定の期間として反映する。 */
  const setRangeParts = useCallback(
    (next: ZonedRangeParts) => {
      setRangeDraft({ key: rangeKey, parts: next })
      const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(next)
      const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
      if (!resolved.ok) {
        setRangeInputError(resolved.message)
        return
      }
      if (!resolved.from || !resolved.to) {
        setRangeInputError(null)
        return
      }
      const reason = validateResolvedRange({ from: resolved.from, to: resolved.to })
      setRangeInputError(reason)
      if (!reason) setFixedRange({ from: resolved.from, to: resolved.to })
    },
    [rangeKey, timeZone, setFixedRange],
  )

  const setVcenterId = useCallback((vcenterId: string) => patch({ vcenterId }), [patch])
  const setMinScore = useCallback((minScore: number) => patch({ minScore }), [patch])
  const setAnchor = useCallback(
    (anchor: string | null) => {
      // 行の時刻は Z の無い表記のことがあるので、UTC の ISO 8601 にそろえて持つ
      const ms = anchor === null ? NaN : parseApiUtcInstantMs(anchor)
      patch({ anchor: Number.isFinite(ms) ? new Date(ms).toISOString() : null })
    },
    [patch],
  )

  /** 種別の切り替え。最後の 1 つは外せない。 */
  const toggleSource = useCallback((kind: TimelineSourceKind) => {
    setConditions((c) => {
      const has = c.sources.includes(kind)
      if (has && c.sources.length === 1) return c
      const next = has ? c.sources.filter((k) => k !== kind) : [...c.sources, kind]
      return { ...c, sources: TIMELINE_SOURCE_KINDS.filter((k) => next.includes(k)) }
    })
  }, [])

  /** 対象で絞る（検索欄の待ち時間を待たずに反映する）。vCenter が分かるときはそれも絞る。 */
  const filterByEntity = useCallback((entityName: string, vcenterId?: string | null) => {
    setEntityInput(entityName)
    setConditions((c) => ({ ...c, entity: entityName, ...(vcenterId ? { vcenterId } : {}) }))
  }, [])

  const clearEntity = useCallback(() => {
    setEntityInput('')
    patch({ entity: '' })
  }, [patch])

  const refresh = useCallback(() => setReloadNonce((n) => n + 1), [])

  /** 保存済みスナップショットの期間と vCenter を条件に反映する（対象・起点は外す）。 */
  const applySnapshotConditions = useCallback(
    (range: ResolvedRange, vcenterId: string) => {
      setEntityInput('')
      setRangeHistory([])
      setRangeInputError(null)
      setConditions((c) => ({
        ...c,
        range: { mode: 'fixed', from: range.from, to: range.to },
        vcenterId,
        entity: '',
        anchor: null,
      }))
    },
    [],
  )

  return {
    timeZone,
    conditions,
    entityInput,
    setEntityInput,
    rangeParts,
    setRangeParts,
    rangeInputError,
    resolvedRange,
    canUndoZoom: rangeHistory.length > 0,
    selectRollingPreset,
    setFixedRange,
    zoomTo,
    undoZoom,
    widen,
    setVcenterId,
    setMinScore,
    setAnchor,
    toggleSource,
    filterByEntity,
    clearEntity,
    refresh,
    applySnapshotConditions,
    data,
    loadedRange,
    loading,
    error,
    sortOrder,
    setSortOrder,
    vcenters,
  }
}
