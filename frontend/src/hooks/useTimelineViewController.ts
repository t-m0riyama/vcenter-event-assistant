import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, apiGet } from '../api'
import { validateApiRange } from '../datetime/apiRangeLimit'
import {
  postIncidentTimelineView,
  TimelineBusyError,
  TimelineRateLimitedError,
  TimelineRequestSupersededError,
} from '../api/incidentTimelineView'
import type {
  IncidentTimelineViewRequest,
  IncidentTimelineViewResponse,
  SavedIncidentTimelineViewRequest,
  VCenter,
} from '../api/schemas'
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
  conditionsFromViewRequest,
  resolveTimelineRange,
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
  TIMELINE_ROLLING_PRESETS,
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

/** `invalid` は期間・URL などの入力の誤り、`busy` は混み合い（503）、`rate_limited` は 429、`error` はそれ以外。 */
export type TimelineLoadError = {
  readonly kind: 'invalid' | 'busy' | 'rate_limited' | 'error'
  readonly message: string
}

type Job = {
  readonly id: number
  readonly body: ReturnType<typeof buildViewRequest> | null
  /** 再試行の待ちを中断するための印。次の要求を予約すると中断する。 */
  readonly abort: AbortController
}

/** 保存済みスナップショットの結果を表示しているときの内容。条件を変えるか再集計すると外れる。 */
export type SavedViewState = {
  readonly snapshotId: string
  readonly note: string
  /** 保存した日時（UTC の ISO 8601）。 */
  readonly savedAt: string
  readonly result: IncidentTimelineViewResponse
  readonly range: ResolvedRange
}

/** 保存済みの結果を読めず、現在のデータで再集計したときの注記。 */
export const SAVED_RESULT_UNREADABLE_NOTICE =
  '保存時点の結果はいまの形式で読めないため、現在のデータで再集計しました。'

function readSortOrder(): TimelineSortOrder {
  try {
    return localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY) === 'asc' ? 'asc' : 'desc'
  } catch {
    return 'desc'
  }
}

function toLoadError(e: unknown): TimelineLoadError {
  if (e instanceof TimelineBusyError) return { kind: 'busy', message: e.message }
  if (e instanceof TimelineRateLimitedError) return { kind: 'rate_limited', message: e.message }
  // 422（件数が多すぎるなど）は同じ条件で読み直しても同じ結果なので、入力の誤りと同じ扱い（読み直しは出さない）。
  // サーバの detail は ApiError が message にしている
  if (e instanceof ApiError && e.status === 422) return { kind: 'invalid', message: e.message }
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
  const [initial] = useState(() => readTimelineHash())
  const [conditions, setConditionsRaw] = useState<TimelineConditions>(
    () => initial?.conditions ?? DEFAULT_TIMELINE_CONDITIONS,
  )
  /** URL の条件が読めなかった理由。あるあいだは読み込まず、URL も書き換えない（条件を変えると消える）。 */
  const [urlIssue, setUrlIssue] = useState<string | null>(() => initial?.issue ?? null)
  const [entityInput, setEntityInput] = useState(conditions.entity)
  const [rangeHistory, setRangeHistory] = useState<readonly TimelineRange[]>([])
  const [reloadNonce, setReloadNonce] = useState(0)
  const [resolvedRange, setResolvedRange] = useState<ResolvedRange>(() =>
    resolveTimelineRange(conditions.range, Date.now()),
  )
  const [data, setData] = useState<IncidentTimelineViewResponse | null>(null)
  /** `data` を取得したときの期間（保存・スナップショットに使う。応答の時刻表記には頼らない）。 */
  const [loadedRange, setLoadedRange] = useState<ResolvedRange | null>(null)
  /** `data` を取得したときに送った本文。スナップショットの保存で、表示中の条件をそのまま送るのに使う。 */
  const [loadedRequest, setLoadedRequest] = useState<IncidentTimelineViewRequest | null>(null)
  /** 保存済みスナップショットの結果を表示中なら、その内容。あいだは自動の読み込みを止める。 */
  const [savedView, setSavedView] = useState<SavedViewState | null>(null)
  /** 保存済みの結果を読めず再集計に落ちたときの注記。条件の変更・再集計・URL の変更で消える。 */
  const [notice, setNotice] = useState<string | null>(null)
  /** 利用者が条件を決め直した回数。詳細の取得中に条件が変わったかを見分け、古い結果で上書きしないために使う。 */
  const intentRef = useRef(0)
  const savedViewActiveRef = useRef(false)
  savedViewActiveRef.current = savedView !== null
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<TimelineLoadError | null>(null)
  const [sortOrder, setSortOrderState] = useState<TimelineSortOrder>(readSortOrder)
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [vcentersLoaded, setVcentersLoaded] = useState(false)
  const [rangeDraft, setRangeDraft] = useState<{ key: string; parts: ZonedRangeParts } | null>(null)
  const [rangeInputError, setRangeInputError] = useState<string | null>(null)

  /** 利用者が条件を変えたとき。URL の読めなかった部分は、この変更で置き換わる。 */
  const setConditions = useCallback((next: (c: TimelineConditions) => TimelineConditions) => {
    intentRef.current += 1
    setUrlIssue(null)
    setNotice(null)
    // 保存済みの結果の表示中に条件を変えたら、通常の表示（現在のデータ）に戻る
    setSavedView(null)
    setConditionsRaw(next)
  }, [])

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
        if (!cancelled) {
          setVcenters(asArray<VCenter>(raw))
          setVcentersLoaded(true)
        }
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
  }, [entityInput, conditions.entity, setConditions])

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
          const res = await postIncidentTimelineView(job.body, job.abort.signal)
          if (isCurrent()) {
            setData(res)
            setLoadedRange({ from: job.body.from, to: job.body.to })
            setLoadedRequest(job.body)
            setError(null)
          }
        } catch (e) {
          if (e instanceof TimelineRequestSupersededError) continue
          if (isCurrent()) {
            setData(null)
            setLoadedRange(null)
            setLoadedRequest(null)
            setError(toLoadError(e))
          }
        }
      }
    } finally {
      runningRef.current = false
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  // ---- URL との同期 -----------------------------------------------------------
  /** 直近に予約した条件（`reloadNonce` を除く）。戻ったときの読み直しが二重にならないよう見分ける。 */
  const scheduledConditionsRef = useRef<string | null>(null)

  const isTimelineHash = () => parseAppHash(window.location.hash).tab === 'timeline'
  const urlIssueRef = useRef(urlIssue)
  urlIssueRef.current = urlIssue

  /** URL の条件を取り込む。条件が変わったら true。 */
  const adoptFromLocation = useCallback((): boolean => {
    if (!isTimelineHash()) return false
    const incoming = readTimelineHash()
    if (!incoming) {
      // タブ切り替えで `#/timeline` に戻った。持っている条件を URL に書き直す
      if (!urlIssueRef.current) replaceTimelineHash(conditionsRef.current)
      return false
    }
    if (
      buildTimelineHash(incoming.conditions) === buildTimelineHash(conditionsRef.current) &&
      incoming.issue === urlIssueRef.current
    ) {
      return false
    }
    intentRef.current += 1
    setSavedView(null)
    setNotice(null)
    setConditionsRaw(incoming.conditions)
    setUrlIssue(incoming.issue)
    setEntityInput(incoming.conditions.entity)
    setRangeHistory([])
    setRangeInputError(null)
    return true
  }, [])

  useEffect(() => {
    const onHashChange = () => {
      adoptFromLocation()
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [adoptFromLocation])

  // 別のタブから戻ったとき（読み込みの effect より先に評価して、戻る前に予約済みだったかを見分ける）: URL（他タブからの入口リンク）を取り込む。条件が変わったなら、それで 1 回読み込む。
  // 変わっていないときは、直近 N 時間のときだけ読み直す（固定の期間の結果は古くならない）
  const skipUrlWriteRef = useRef(false)
  const wasActiveRef = useRef(active)
  useEffect(() => {
    if (active && !wasActiveRef.current) {
      skipUrlWriteRef.current = true
      const changed = adoptFromLocation()
      const alreadyScheduled =
        scheduledConditionsRef.current === JSON.stringify({ conditions: conditionsRef.current, urlIssue: urlIssueRef.current })
      if (!changed && conditionsRef.current.range.mode === 'rolling' && alreadyScheduled) {
        setReloadNonce((n) => n + 1)
      }
    }
    wasActiveRef.current = active
  }, [active, adoptFromLocation])

  // 表示に切り替わった直後は、URL に別タブからの入口リンクの条件が来ているかもしれない。
  // 持っている条件で上書きする前に取り込む（取り込みは上の effect で行い、そのコミットでは書き込まない）
  useEffect(() => {
    if (skipUrlWriteRef.current) {
      skipUrlWriteRef.current = false
      return
    }
    // URL が読めなかったあいだは書き換えない（共有リンクの条件を消さない）
    if (active && !urlIssue && isTimelineHash()) replaceTimelineHash(conditions)
  }, [active, conditions, urlIssue])

  const loadKey = useMemo(
    () => JSON.stringify({ conditions, urlIssue, reloadNonce }),
    [conditions, urlIssue, reloadNonce],
  )

  useEffect(() => {
    if (!active) return
    // 保存済みの結果を表示しているあいだは読み込まない（再集計か条件の変更で外れたときに読む）
    if (savedViewActiveRef.current) return
    // StrictMode の二重実行や、同じ条件での再実行で同じ要求を重ねない（更新ボタンは reloadNonce で変わる）
    if (lastKeyRef.current === loadKey) return
    lastKeyRef.current = loadKey
    scheduledConditionsRef.current = JSON.stringify({ conditions: conditionsRef.current, urlIssue })
    // 前の要求の再試行待ちは、新しい条件を待たせないよう中断する
    desiredRef.current?.abort.abort()
    const abort = new AbortController()
    const range = resolveTimelineRange(conditionsRef.current.range, Date.now())
    setResolvedRange(range)
    const invalid = urlIssue ?? validateApiRange(range)
    if (invalid) {
      desiredRef.current = { id: ++jobCounterRef.current, body: null, abort }
      setData(null)
      setLoadedRange(null)
      setLoadedRequest(null)
      setError({ kind: 'invalid', message: invalid })
      void pump()
      return
    }
    desiredRef.current = {
      id: ++jobCounterRef.current,
      body: buildViewRequest(conditionsRef.current, range),
      abort,
    }
    // 前の条件のエラーを残さない（次の結果かエラーが来るまで読み込み中として見せる）
    setError(null)
    setLoading(true)
    void pump()
  }, [active, loadKey, pump, urlIssue, savedView])

  // ---- 条件の変更 -------------------------------------------------------------
  const patch = useCallback((next: Partial<TimelineConditions>) => {
    setConditions((c) => ({ ...c, ...next }))
  }, [setConditions])

  const setRange = useCallback((range: TimelineRange, keepHistory: boolean) => {
    if (!keepHistory) setRangeHistory([])
    setConditions((c) => ({ ...c, range }))
  }, [setConditions])

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
  }, [setConditions])

  const undoZoom = useCallback(() => {
    const previous = rangeHistory[rangeHistory.length - 1]
    if (!previous) return
    setRangeInputError(null)
    setRangeHistory((h) => h.slice(0, -1))
    setConditions((c) => ({ ...c, range: previous }))
  }, [rangeHistory, setConditions])

  const widen = useCallback(() => {
    const range = conditionsRef.current.range
    if (range.mode === 'rolling') {
      // 直近 N 時間は、次のプリセット（1 → 6 → 24 時間）へ。24 時間を超えるときだけ固定の期間にする
      const next = TIMELINE_ROLLING_PRESETS.find((p) => p.durationMs > range.durationMs)
      if (next) {
        selectRollingPreset(next.durationMs)
        return
      }
    }
    setFixedRange(widenRange(resolveTimelineRange(range, Date.now()), range))
  }, [selectRollingPreset, setFixedRange])

  const rangeKey = JSON.stringify(conditions.range)
  const derivedParts = useMemo(
    () => zonedRangePartsFromUtcIsoEndpoints(resolvedRange.from, resolvedRange.to, timeZone),
    [resolvedRange, timeZone],
  )
  const rangeParts = rangeDraft && rangeDraft.key === rangeKey ? rangeDraft.parts : derivedParts

  /** 期間の入力欄の編集。確定は {@link applyRangeParts}（「適用」ボタンか Enter）で行う。 */
  const setRangeParts = useCallback(
    (next: ZonedRangeParts) => {
      setRangeDraft({ key: rangeKey, parts: next })
      setRangeInputError(null)
    },
    [rangeKey],
  )

  /**
   * 入力欄の期間を固定の期間として確定する。編集していない側は、今の期間の時刻（秒を含む）をそのまま使う
   * （入力欄は分までしか持たないので、通すと秒が落ちる）。
   */
  const applyRangeParts = useCallback(() => {
    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      setRangeInputError(resolved.message)
      return
    }
    if (!resolved.from || !resolved.to) {
      setRangeInputError('期間の開始と終了の両方を入力してください。')
      return
    }
    const same = (a: ZonedRangeParts, b: ZonedRangeParts, side: 'from' | 'to') =>
      side === 'from'
        ? a.fromDate === b.fromDate && a.fromTime === b.fromTime
        : a.toDate === b.toDate && a.toTime === b.toTime
    const next = {
      from: same(rangeParts, derivedParts, 'from') ? resolvedRange.from : resolved.from,
      to: same(rangeParts, derivedParts, 'to') ? resolvedRange.to : resolved.to,
    }
    const reason = validateApiRange(next)
    setRangeInputError(reason)
    if (!reason) setFixedRange(next)
  }, [rangeParts, derivedParts, resolvedRange, timeZone, setFixedRange])

  const setVcenterId = useCallback((vcenterId: string) => patch({ vcenterId }), [patch])
  const setMinScore = useCallback((minScore: number) => patch({ minScore }), [patch])
  const setCpuThreshold = useCallback((cpuThresholdPct: number) => patch({ cpuThresholdPct }), [patch])
  const setMemoryThreshold = useCallback((memoryThresholdPct: number) => patch({ memoryThresholdPct }), [patch])
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
  }, [setConditions])

  /** 対象で絞る（検索欄の待ち時間を待たずに反映する）。vCenter が分かるときはそれも絞る。 */
  const filterByEntity = useCallback((entityName: string, vcenterId?: string | null) => {
    setEntityInput(entityName)
    setConditions((c) => ({ ...c, entity: entityName, ...(vcenterId ? { vcenterId } : {}) }))
  }, [setConditions])

  const clearEntity = useCallback(() => {
    setEntityInput('')
    patch({ entity: '' })
  }, [patch])

  const refresh = useCallback(() => {
    // 保存済みの結果の表示中は「更新」で現在のデータに入れ替えない（再集計は専用の操作）
    if (savedViewActiveRef.current) return
    setReloadNonce((n) => n + 1)
  }, [])

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
    [setConditions],
  )

  /**
   * 保存済みスナップショットの結果をそのまま表示する。条件は保存時の `view_request` に合わせる
   * （URL にも反映）。進行中の読み込みは捨て、現在のデータは取りに行かない。
   */
  const showSavedResult = useCallback(
    (saved: Omit<SavedViewState, 'range'>, request: SavedIncidentTimelineViewRequest) => {
      const conditions = conditionsFromViewRequest(request)
      intentRef.current += 1
      desiredRef.current?.abort.abort()
      desiredRef.current = null
      lastKeyRef.current = null
      // 外したあとに、開く前の別の条件の結果が出ないよう、通常の表示の結果も捨てる
      setData(null)
      setLoadedRange(null)
      setLoadedRequest(null)
      setNotice(null)
      setEntityInput(conditions.entity)
      setRangeHistory([])
      setRangeInputError(null)
      setUrlIssue(null)
      setConditionsRaw(conditions)
      if (conditions.range.mode !== 'fixed') return
      const range = { from: conditions.range.from, to: conditions.range.to }
      // 読み込みの effect は保存済みの表示中は動かないので、条件バーの期間（表示・入力欄・「適用」の基準）は
      // ここで保存した期間に合わせる。入力途中の値も捨てる
      setResolvedRange(range)
      setRangeDraft(null)
      setSavedView({ ...saved, range })
      setLoading(false)
    },
    [],
  )

  /** 保存時の `view_request` の条件へ戻して、現在のデータで集計し直す（保存済みの結果の表示ではないとき）。 */
  const applyViewRequest = useCallback(
    (request: SavedIncidentTimelineViewRequest, options: { notice?: string } = {}) => {
      const conditions = conditionsFromViewRequest(request)
      setEntityInput(conditions.entity)
      setRangeHistory([])
      setRangeInputError(null)
      setConditions(() => conditions)
      // setConditions は注記を消すので、あとから入れる
      if (options.notice) setNotice(options.notice)
    },
    [setConditions],
  )

  /** 保存済みの結果の表示をやめ、同じ条件で現在のデータを読み直す。 */
  const reaggregate = useCallback(() => {
    intentRef.current += 1
    lastKeyRef.current = null
    setSavedView(null)
    setNotice(null)
    setReloadNonce((n) => n + 1)
  }, [])

  const showingSaved = savedView !== null

  /** 現在の「利用者の意図」の通し番号。取得の前後で変わっていたら、取得した内容は使わない。 */
  const getIntent = useCallback(() => intentRef.current, [])

  return {
    notice,
    getIntent,
    savedView,
    showSavedResult,
    applyViewRequest,
    reaggregate,
    timeZone,
    conditions,
    entityInput,
    setEntityInput,
    rangeParts,
    setRangeParts,
    applyRangeParts,
    urlIssue,
    vcentersLoaded,
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
    setCpuThreshold,
    setMemoryThreshold,
    setAnchor,
    toggleSource,
    filterByEntity,
    clearEntity,
    refresh,
    applySnapshotConditions,
    data: savedView ? savedView.result : data,
    loadedRange: savedView ? savedView.range : loadedRange,
    // 保存済みの結果の表示中は、保存できない（現在のデータの条件ではないため）
    loadedRequest: savedView ? null : loadedRequest,
    loading: showingSaved ? false : loading,
    error: showingSaved ? null : error,
    sortOrder,
    setSortOrder,
    vcenters,
  }
}
