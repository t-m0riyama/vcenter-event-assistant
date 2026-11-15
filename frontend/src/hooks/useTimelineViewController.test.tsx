import { act, renderHook, waitFor } from '@testing-library/react'
import { StrictMode, type ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../datetime/TimeZoneProvider'
import { buildTimelineHash } from '../routing/timelineHash'
import {
  emptyViewResponse,
  installTimelineFetchMock,
  jsonResponse,
  VIEW_RESPONSE_EXAMPLE,
} from '../test/timelineViewFixtures'
import {
  TIMELINE_ENTITY_DEBOUNCE_MS,
  TIMELINE_SORT_ORDER_STORAGE_KEY,
  useTimelineViewController,
} from './useTimelineViewController'

function wrapper({ children }: { children: ReactNode }) {
  return <TimeZoneProvider>{children}</TimeZoneProvider>
}

function strictWrapper({ children }: { children: ReactNode }) {
  return (
    <StrictMode>
      <TimeZoneProvider>{children}</TimeZoneProvider>
    </StrictMode>
  )
}

/** 呼び出しごとに作り直すと vCenter 一覧の effect が再実行され続けるので、安定した関数を渡す。 */
const onError = vi.fn()
const VC_A = '11111111-1111-4111-8111-11111111111a'
const VC_B = '11111111-1111-4111-8111-11111111111b'
const VC_C = '11111111-1111-4111-8111-11111111111c'
const T0 = Date.parse('2026-03-22T01:00:00Z')

describe('useTimelineViewController', () => {
  let harness: ReturnType<typeof installTimelineFetchMock>

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: T0 })
    localStorage.clear()
    window.history.replaceState(null, '', '/#/timeline')
    harness = installTimelineFetchMock()
    vi.stubGlobal('fetch', vi.fn(harness.fetchMock))
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const answer = async (index: number, data: unknown = emptyViewResponse()) => {
    await waitFor(() => expect(harness.calls.length).toBeGreaterThan(index))
    await act(async () => {
      harness.calls[index].resolve(jsonResponse(data))
    })
  }

  it('開いたときに直近 1 時間を自動で読み込み、URL を range=1h にする', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(harness.calls[0].body).toMatchObject({
      from: '2026-03-22T00:00:00.000Z',
      to: '2026-03-22T01:00:00.000Z',
      sources: ['event', 'alert', 'metric', 'log'],
      metric_threshold_cpu_pct: 80,
      metric_threshold_memory_pct: 85,
    })
    expect(result.current.loading).toBe(true)
    await answer(0, VIEW_RESPONSE_EXAMPLE)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data?.items).toHaveLength(2)
    expect(window.location.hash).toBe('#/timeline?range=1h')
  })

  it('URL の固定の期間・起点・対象を復元して、その条件で読み込む', async () => {
    window.history.replaceState(
      null,
      '',
      `/#/timeline?from=2026-03-20T00:00:00.000Z&to=2026-03-20T06:00:00.000Z&anchor=2026-03-20T03:00:00.000Z&vcenter_id=${VC_A}&entity=esx01`,
    )
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(harness.calls[0].body).toMatchObject({
      from: '2026-03-20T00:00:00.000Z',
      to: '2026-03-20T06:00:00.000Z',
      anchor: '2026-03-20T03:00:00.000Z',
      vcenter_id: VC_A,
      entity: 'esx01',
    })
    expect(result.current.conditions.range.mode).toBe('fixed')
  })

  it('条件を変えると読み直し、URL が追従する（プリセットは range、固定は from/to、履歴は増えない）', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    const historyLength = window.history.length
    act(() => result.current.selectRollingPreset(6 * 3_600_000))
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=6h'))
    await answer(1)
    // 時計は shouldAdvanceTime で少し進むので、6 時間前の近くであることを確かめる
    expect(Math.abs(Date.parse(String(harness.calls[1].body.from)) - (T0 - 6 * 3_600_000))).toBeLessThan(2000)
    act(() =>
      result.current.setFixedRange({ from: '2026-03-21T10:00:00.000Z', to: '2026-03-21T11:00:00.000Z' }),
    )
    await waitFor(() => expect(window.location.hash).toContain('from=2026-03-21T10%3A00%3A00.000Z'))
    expect(window.location.hash).not.toContain('range=')
    await answer(2)
    expect(window.history.length).toBe(historyLength)
  })

  it('読み込み中に条件が変わったら、古い応答では表示を上書きしない（1 本ずつ送る）', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    act(() => result.current.setVcenterId(VC_B))
    act(() => result.current.setVcenterId(VC_C))
    // 古い要求が終わるまで、次は送らない（サーバの同時実行数は 1）
    expect(harness.calls).toHaveLength(1)
    await answer(0, emptyViewResponse({ total_items: 111 }))
    expect(result.current.data).toBeNull()
    // 途中の vc-b は飛ばして、最新の条件だけを送る
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(harness.calls[1].body.vcenter_id).toBe(VC_C)
    await answer(1, emptyViewResponse({ total_items: 222 }))
    await waitFor(() => expect(result.current.data?.total_items).toBe(222))
    expect(result.current.loading).toBe(false)
  })

  it('対象の検索欄は入力が止まってから 1 回だけ読み込む', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.setEntityInput('e'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    act(() => result.current.setEntityInput('esx'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMELINE_ENTITY_DEBOUNCE_MS - 100)
    })
    expect(harness.calls).toHaveLength(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(harness.calls[1].body.entity).toBe('esx')
    expect(window.location.hash).toContain('entity=esx')
  })

  it('対象で絞る操作は待たずに反映し、vCenter も絞る', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.filterByEntity('vm-a', VC_A))
    await answer(1)
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC_A })
    expect(result.current.entityInput).toBe('vm-a')
  })

  it('503 は待って 1 回だけ自動で再試行し、成功すれば表示する', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: 'busy' }, 503, { 'Retry-After': '2' }))
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    await answer(1, emptyViewResponse({ total_items: 7 }))
    await waitFor(() => expect(result.current.data?.total_items).toBe(7))
    expect(result.current.error).toBeNull()
  })

  it('503 が再試行でも続けば「混み合っています」のエラーにする', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({}, 503))
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100)
    })
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    await act(async () => {
      harness.calls[1].resolve(jsonResponse({}, 503))
    })
    await waitFor(() => expect(result.current.error?.kind).toBe('busy'))
    expect(result.current.error?.message).toContain('混み合って')
  })

  it('429 は自動で再試行せず、レート制限の専用の文言にする', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: 'Too many requests' }, 429))
    })
    await waitFor(() => expect(result.current.error?.kind).toBe('rate_limited'))
    expect(result.current.error?.message).toContain('短時間に操作が多すぎます')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000)
    })
    expect(harness.calls).toHaveLength(1)
  })

  it('503 の再試行を待っている間に条件が変わったら、待たずに新しい条件を送る', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({}, 503, { 'Retry-After': '9' }))
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    act(() => result.current.setVcenterId(VC_B))
    // 9 秒を待たずに新しい条件の要求が出る（古い条件の再試行は出ない）
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(harness.calls[1].body.vcenter_id).toBe(VC_B)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(harness.calls).toHaveLength(2)
  })

  it('エラーの後に条件を変えたら、次の要求を予約した時点で前のエラーを消す', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: '集計できません' }, 422))
    })
    await waitFor(() => expect(result.current.error).not.toBeNull())
    act(() => result.current.setVcenterId(VC_B))
    expect(result.current.error).toBeNull()
    await waitFor(() => expect(harness.calls).toHaveLength(2))
  })

  it('422 はサーバの detail をそのまま出す', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(
        jsonResponse({ detail: 'イベントの種類が多すぎて集計できません。vCenter を指定して絞り込んでください。' }, 422),
      )
    })
    await waitFor(() => expect(result.current.error).not.toBeNull())
    expect(result.current.error).toEqual({
      kind: 'error',
      message: 'イベントの種類が多すぎて集計できません。vCenter を指定して絞り込んでください。',
    })
  })

  it('期間が不正なら API を呼ばずに理由を出す', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.setFixedRange({ from: '2026-03-22T01:00:00.000Z', to: '2026-03-22T01:00:00.500Z' }))
    await waitFor(() => expect(result.current.error?.kind).toBe('invalid'))
    expect(harness.calls).toHaveLength(1)
  })

  it('StrictMode の二重実行でも最初の読み込みは 1 回', async () => {
    renderHook(() => useTimelineViewController(onError), { wrapper: strictWrapper })
    await waitFor(() => expect(harness.calls.length).toBeGreaterThan(0))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(50)
    })
    expect(harness.calls).toHaveLength(1)
  })

  it('更新は同じ条件でも読み直す', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.refresh())
    await waitFor(() => expect(harness.calls).toHaveLength(2))
  })

  it('絞り込み（俯瞰からの期間指定）を元に戻せる', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    expect(result.current.canUndoZoom).toBe(false)
    act(() => result.current.zoomTo({ from: '2026-03-22T00:10:00.000Z', to: '2026-03-22T00:11:00.000Z' }))
    await answer(1)
    expect(result.current.canUndoZoom).toBe(true)
    expect(window.location.hash).toContain('from=')
    act(() => result.current.undoZoom())
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=1h'))
    expect(result.current.canUndoZoom).toBe(false)
  })

  it('タブが表示中でないときは URL を書かず、読み込みもしない。戻ったら URL を書き直して読み直す', async () => {
    window.history.replaceState(null, '', '/#/events?vcenter_id=x&from=a&to=b')
    const { rerender } = renderHook(({ active }) => useTimelineViewController(onError, { active }), {
      wrapper,
      initialProps: { active: false },
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(harness.calls).toHaveLength(0)
    expect(window.location.hash).toBe('#/events?vcenter_id=x&from=a&to=b')
    // タブを開き直すと App は `#/timeline` に置き換える
    window.history.replaceState(null, '', '/#/timeline')
    rerender({ active: true })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(window.location.hash).toBe('#/timeline?range=1h')
  })

  it('他のタブからの入口リンク（hashchange）の条件を取り込んで読み込む', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    const hash = buildTimelineHash({
      ...result.current.conditions,
      range: { mode: 'fixed', from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T00:30:00.000Z' },
      anchor: '2026-03-22T00:15:00.000Z',
      entity: 'vm-z',
    })
    act(() => {
      window.history.replaceState(null, '', `/${hash}`)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await answer(1)
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-z', anchor: '2026-03-22T00:15:00.000Z' })
    expect(result.current.entityInput).toBe('vm-z')
  })

  it('並び順は localStorage に覚える（キーは旧画面と同じ）', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    expect(result.current.sortOrder).toBe('desc')
    act(() => result.current.setSortOrder('asc'))
    expect(localStorage.getItem(TIMELINE_SORT_ORDER_STORAGE_KEY)).toBe('asc')
    expect(TIMELINE_SORT_ORDER_STORAGE_KEY).toBe('vea.timeline.sort_order')
  })

  it('最後の 1 つの種別は外せない', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    for (const kind of ['alert', 'metric', 'log'] as const) act(() => result.current.toggleSource(kind))
    expect(result.current.conditions.sources).toEqual(['event'])
    act(() => result.current.toggleSource('event'))
    expect(result.current.conditions.sources).toEqual(['event'])
  })

  it('種別の切り替えは要求の本文と URL に反映され、既定（4 種類）に戻すと URL から消える', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0, VIEW_RESPONSE_EXAMPLE)
    act(() => {
      result.current.toggleSource('event')
      result.current.toggleSource('alert')
    })
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=1h&sources=metric%2Clog'))
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(harness.calls[1].body.sources).toEqual(['metric', 'log'])
    await answer(1, VIEW_RESPONSE_EXAMPLE)
    act(() => {
      result.current.toggleSource('alert')
      result.current.toggleSource('event')
    })
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=1h'))
  })

  it('メトリクスのしきい値は要求の本文と URL に反映され、既定に戻すと URL から消える', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0, VIEW_RESPONSE_EXAMPLE)
    act(() => {
      result.current.setCpuThreshold(90)
      result.current.setMemoryThreshold(70.5)
    })
    await waitFor(() =>
      expect(window.location.hash).toBe('#/timeline?range=1h&cpu_threshold=90&memory_threshold=70.5'),
    )
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(harness.calls[1].body).toMatchObject({ metric_threshold_cpu_pct: 90, metric_threshold_memory_pct: 70.5 })
    await answer(1, VIEW_RESPONSE_EXAMPLE)
    act(() => {
      result.current.setCpuThreshold(80)
      result.current.setMemoryThreshold(85)
    })
    await waitFor(() => expect(window.location.hash).toBe('#/timeline?range=1h'))
  })

  it('URL の種別としきい値を復元して、その条件で読み込む', async () => {
    window.history.replaceState(null, '', '/#/timeline?range=1h&sources=metric,log&cpu_threshold=95')
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(harness.calls[0].body).toMatchObject({
      sources: ['metric', 'log'],
      metric_threshold_cpu_pct: 95,
      metric_threshold_memory_pct: 85,
    })
    expect(result.current.conditions.cpuThresholdPct).toBe(95)
  })

  it.each([
    ['逆順の期間', '#/timeline?from=2026-03-22T02:00:00Z&to=2026-03-22T01:00:00Z', '開始'],
    ['片方だけの期間', '#/timeline?from=2026-03-22T02:00:00Z', '両方'],
    ['UUID でない vcenter_id', '#/timeline?range=1h&vcenter_id=abc', 'UUID'],
  ])('URL が不正（%s）なら API を呼ばずに理由を出し、URL を書き換えない', async (_name, hash, reason) => {
    window.history.replaceState(null, '', `/${hash}`)
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(result.current.error?.kind).toBe('invalid'))
    expect(result.current.error?.message).toContain(reason)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(harness.calls).toHaveLength(0)
    expect(window.location.hash).toBe(hash)
    // 利用者が条件を変えると、その条件で読み込み、URL も書き直す
    act(() => result.current.selectRollingPreset(6 * 3_600_000))
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(result.current.error).toBeNull()
    expect(window.location.hash).toBe('#/timeline?range=6h')
  })

  it('Z の無い URL の時刻は UTC として読み込む', async () => {
    window.history.replaceState(null, '', '/#/timeline?from=2026-03-22T00:00:00&to=2026-03-22T01:00:00')
    renderHook(() => useTimelineViewController(onError), { wrapper })
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(harness.calls[0].body).toMatchObject({ from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T01:00:00.000Z' })
  })

  it('不正な URL が hashchange で来ても、読み込まず URL を書き換えない', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    const bad = '#/timeline?from=2026-03-22T02:00:00Z&to=2026-03-22T01:00:00Z'
    act(() => {
      window.history.replaceState(null, '', `/${bad}`)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(result.current.error?.kind).toBe('invalid'))
    expect(window.location.hash).toBe(bad)
    expect(harness.calls).toHaveLength(1)
  })

  it('入口リンク（hashchange）で条件を取り込んだときの読み込みは 1 回だけ', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => {
      window.history.replaceState(
        null,
        '',
        '/#/timeline?from=2026-03-22T00:00:00.000Z&to=2026-03-22T00:30:00.000Z&entity=vm-z',
      )
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await answer(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(harness.calls).toHaveLength(2)
    expect(result.current.conditions.entity).toBe('vm-z')
  })

  it('タブに戻ったときの読み直しは直近 N 時間のときだけ（固定の期間では読み直さない）', async () => {
    window.history.replaceState(null, '', '/#/timeline?from=2026-03-22T00:00:00.000Z&to=2026-03-22T01:00:00.000Z')
    const { rerender } = renderHook(({ active }) => useTimelineViewController(onError, { active }), {
      wrapper,
      initialProps: { active: true },
    })
    await answer(0)
    rerender({ active: false })
    window.history.replaceState(null, '', '/#/timeline')
    rerender({ active: true })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(harness.calls).toHaveLength(1)
    expect(window.location.hash).toContain('from=2026-03-22T00%3A00%3A00.000Z')
  })

  it('タブが非表示のあいだに入口リンクが来て、戻ったときは新しい条件で 1 回だけ読み込む', async () => {
    const { rerender } = renderHook(({ active }) => useTimelineViewController(onError, { active }), {
      wrapper,
      initialProps: { active: true },
    })
    await answer(0)
    rerender({ active: false })
    act(() => {
      window.history.replaceState(null, '', '/#/timeline?range=1h&entity=vm-q')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    rerender({ active: true })
    await answer(1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(harness.calls).toHaveLength(2)
    expect(harness.calls[1].body.entity).toBe('vm-q')
  })

  it('タブの表示が先に切り替わっても（hashchange の取り込みより前でも）、入口リンクの条件を URL から消さない', async () => {
    const { rerender, result } = renderHook(({ active }) => useTimelineViewController(onError, { active }), {
      wrapper,
      initialProps: { active: true },
    })
    await answer(0)
    rerender({ active: false })
    // hashchange を配る前に、アプリがタブを表示に切り替える順序
    window.history.replaceState(null, '', '/#/timeline?range=1h&entity=vm-q')
    rerender({ active: true })
    expect(window.location.hash).toContain('entity=vm-q')
    await answer(1)
    expect(harness.calls[1].body.entity).toBe('vm-q')
    expect(result.current.conditions.entity).toBe('vm-q')
    // 読み込みが重複していない（最初の 1 回と、入口リンクの条件での 1 回だけ）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })
    expect(harness.calls).toHaveLength(2)
  })

  it('期間の入力欄は「適用」まで確定せず、編集していない側の秒を落とさない', async () => {
    window.history.replaceState(
      null,
      '',
      '/#/timeline?from=2026-03-22T00:00:30.000Z&to=2026-03-22T01:00:45.000Z',
    )
    localStorage.setItem('vea.displayTimeZone', 'UTC')
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.setRangeParts({ ...result.current.rangeParts, toTime: '02:00' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    expect(harness.calls).toHaveLength(1) // 入力しただけでは読み込まない
    act(() => result.current.applyRangeParts())
    await answer(1)
    expect(harness.calls[1].body.from).toBe('2026-03-22T00:00:30.000Z') // 触っていない側の秒は保つ
    expect(harness.calls[1].body.to).toBe('2026-03-22T02:00:59.000Z') // 編集した側は分の末尾まで
  })

  it('期間の入力が片方だけのときは適用せず理由を出し、絞り込みを戻すと消える', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.setRangeParts({ fromDate: '', fromTime: '', toDate: '', toTime: '' }))
    act(() => result.current.applyRangeParts())
    expect(result.current.rangeInputError).toContain('両方')
    expect(harness.calls).toHaveLength(1)
    act(() => result.current.zoomTo({ from: '2026-03-22T00:10:00.000Z', to: '2026-03-22T00:11:00.000Z' }))
    await answer(1)
    act(() => result.current.setRangeParts({ fromDate: '', fromTime: '', toDate: '', toTime: '' }))
    act(() => result.current.applyRangeParts())
    expect(result.current.rangeInputError).not.toBeNull()
    act(() => result.current.undoZoom())
    expect(result.current.rangeInputError).toBeNull()
  })

  it('期間を広げる: 直近は 1 → 6 → 24 時間と進み、24 時間を超えるときだけ固定の期間になる', async () => {
    const { result } = renderHook(() => useTimelineViewController(onError), { wrapper })
    await answer(0)
    act(() => result.current.widen())
    expect(result.current.conditions.range).toEqual({ mode: 'rolling', durationMs: 6 * 3_600_000 })
    await answer(1)
    act(() => result.current.widen())
    expect(result.current.conditions.range).toEqual({ mode: 'rolling', durationMs: 24 * 3_600_000 })
    await answer(2)
    act(() => result.current.widen())
    expect(result.current.conditions.range.mode).toBe('fixed')
  })
})
