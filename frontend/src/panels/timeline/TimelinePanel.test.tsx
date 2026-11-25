import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TimelineDetectedPattern, TimelineViewItem } from '../../api/schemas'
import { AUTH_DISABLED_ME, AuthContext } from '../../auth/authContext'
import { INCIDENT_ID, INCIDENT_LIST, INCIDENT_TITLE } from '../../test/incidentFixtures'
import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { TIMELINE_ENTITY_DEBOUNCE_MS } from '../../hooks/useTimelineViewController'
import { timelineEntryHash } from '../../routing/timelineHash'
import { ThemeProvider } from '../../theme/ThemeProvider'
import {
  emptyViewResponse,
  installTimelineFetchMock,
  jsonResponse,
  LOG_ITEM_EXAMPLE,
  METRIC_ITEM_EXAMPLE,
  METRIC_ITEM_LEGACY_EXAMPLE,
  NEW_LOG_PATTERN_EXAMPLE,
  VIEW_RESPONSE_EXAMPLE,
} from '../../test/timelineViewFixtures'
import { TimelinePanel } from './TimelinePanel'

const TEST_TIMEOUT_MS = 15_000
const VC = '11111111-1111-4111-8111-111111111111'
const FIXED_IMPACT_HASH = `/#/timeline?vcenter_id=${VC}&entity_moid=vm-10&from=2026-03-22T00:00:00Z&to=2026-03-22T01:00:00Z`
const DETECTED_PATTERN: TimelineDetectedPattern = {
  pattern_id: 'host-conn-flapping',
  title: 'ホストの切断の繰り返し',
  description: 'ホストの管理ネットワークを確認してください。',
  level: 'error',
  vcenter_id: VC,
  vcenter_name: 'vc-pattern',
  entity_moid: 'host-10',
  entity_name: 'esx-pattern',
  entity_type: 'HostSystem',
  first_utc: '2026-03-21T23:55:00',
  last_utc: '2026-03-22T00:15:00Z',
  event_count: 3,
  event_ids: [11, 12, 13],
}

const CONFIG_CHANGE = {
  kind: 'vm_reconfigure',
  label: 'VM の構成変更',
  first_utc: '2026-03-22T00:08:00Z',
  last_utc: '2026-03-22T00:10:00Z',
  vcenter_id: VC,
  vcenter_name: 'vc-change',
  entity_moid: 'vm-20',
  entity_name: 'vm-change',
  entity_type: 'VirtualMachine',
  user_names: ['operator-a', 'operator-b'],
  event_types: ['vim.event.VmReconfiguredEvent', 'task.success.VirtualMachine.reconfigure'],
  event_count: 3,
  event_ids: [99, 3, 1],
}

function bucket(start: string, total = 0, notable = 0, alert = 0) {
  return {
    bucket_start_utc: start,
    event_total: total,
    event_notable: notable,
    alert,
    metric_breach: 0,
    log_error: 0,
  }
}

/** 3 本の棒と 3 行（2 行はイベント、1 行は VM 無しのアラート）を持つ応答。 */
function populated(
  overrides: Record<string, unknown> = {},
  firstItem: Partial<Pick<TimelineViewItem, 'vcenter_id' | 'ref' | 'timestamp_utc'>> = {},
) {
  const items = [
    {
      id: 'event:1',
      kind: 'event',
      timestamp_utc: '2026-03-22T00:10:00',
      end_utc: '2026-03-22T00:14:00',
      level: 'warning',
      title: 'VmPoweredOffEvent',
      detail: 'vm-a was powered off\nby operator',
      entity_name: 'vm-a',
      entity_type: 'VirtualMachine',
      vcenter_id: VC,
      vcenter_name: 'vc-main',
      score: 55,
      count: 3,
      ref: { event_id: 1, event_type: 'VmPoweredOffEvent', entity_moid: 'vm-10' },
      ...firstItem,
    },
    {
      id: 'alert:2',
      kind: 'alert',
      timestamp_utc: '2026-03-22T00:30:00Z',
      level: 'critical',
      title: 'CPU 高負荷: 発火',
      detail: null,
      entity_name: null,
      vcenter_id: null,
      count: 1,
      ref: { alert_history_id: 2, alert_rule_name: 'CPU 高負荷', alert_state: 'firing' },
    },
    {
      id: 'event:3',
      kind: 'event',
      timestamp_utc: '2026-03-22T00:50:00Z',
      level: 'info',
      title: 'UserLoginSessionEvent',
      detail: 'login',
      entity_name: 'esx01',
      vcenter_id: VC,
      vcenter_name: 'vc-main',
      score: 5,
      count: 1,
      ref: { event_id: 3, event_type: 'UserLoginSessionEvent' },
    },
  ]
  return emptyViewResponse({
    from_utc: '2026-03-22T00:00:00Z',
    to_utc: '2026-03-22T01:00:00Z',
    bucket_seconds: 1200,
    overview: [
      bucket('2026-03-22T00:00:00Z', 4, 2),
      bucket('2026-03-22T00:20:00Z', 1, 0, 1),
      bucket('2026-03-22T00:40:00Z', 1, 0),
    ],
    items,
    total_items: 3,
    highlights: {
      first_signal: items[0],
      top_entities: [
        { entity_name: 'vm-a', entity_moid: 'vm-10', vcenter_id: VC, vcenter_name: 'vc-main', item_count: 3, first_seen_utc: '2026-03-22T00:10:00Z' },
      ],
      new_event_types: [
        { event_type: 'VmPoweredOffEvent', count: 3, first_seen_utc: '2026-03-22T00:10:00Z', max_score: 55 },
      ],
    },
    ...overrides,
  })
}

const onError = vi.fn()

function renderTimeline(
  extra: { onOpenSnapshotInMetrics?: (item: never) => void; onOpenInMetrics?: (focus: never) => void; onOpenInChat?: (focus: never) => void; active?: boolean } = {},
) {
  return render(
    <ThemeProvider>
      <TimeZoneProvider>
        <TimelinePanel onError={onError} {...extra} />
      </TimeZoneProvider>
    </ThemeProvider>,
  )
}

describe('TimelinePanel', { timeout: TEST_TIMEOUT_MS }, () => {
  let harness: ReturnType<typeof installTimelineFetchMock>

  const setup = (options: Parameters<typeof installTimelineFetchMock>[0] = {}) => {
    harness = installTimelineFetchMock(options)
    vi.stubGlobal('fetch', vi.fn(harness.fetchMock))
  }
  const answer = async (index: number, data: unknown = populated()) => {
    await waitFor(() => expect(harness.calls.length).toBeGreaterThan(index))
    await act(async () => {
      harness.calls[index].resolve(jsonResponse(data))
    })
  }
  const mainExport = () => within(screen.getByRole('group', { name: '調査資料を出力' }))
  const markdownExport = { name: '調査資料を Markdown で出力' }
  const zipExport = { name: '調査資料を ZIP で出力' }
  /** 時系列リストの行のボタン（ハイライトの同名ボタンと区別する）。 */
  const rowButton = async (name: RegExp) =>
    within(await screen.findByRole('list', { name: '出来事の時系列' })).getByRole('button', { name })
  const openFirstRow = async () => {
    const button = await rowButton(/VmPoweredOffEvent/)
    fireEvent.click(button)
    return button
  }

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    localStorage.clear()
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'UTC')
    window.history.replaceState(null, '', '/#/timeline')
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('対象名だけで絞ったときは影響範囲の欄も要求も出さない', async () => {
    setup()
    const impact = vi.fn(() => jsonResponse({}))
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', timelineEntryHash({ at: '2026-03-22T00:30:00Z', vcenterId: VC, entity: 'vm-a' }))
    renderTimeline()
    await answer(0)
    expect(harness.calls[0].body.entity).toBe('vm-a')
    expect(impact).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: '影響範囲' })).not.toBeInTheDocument()
  })

  it('影響範囲は最新のタイムラインの応答を待ち、その期間と最初の兆候を使う', async () => {
    setup()
    const impact = vi.fn((url: string) => jsonResponse({ detail: url }, 404))
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', `/#/timeline?vcenter_id=${VC}&entity_moid=vm-10`)
    renderTimeline()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(impact).not.toHaveBeenCalled()
    await answer(0)
    await screen.findByText('この vCenter は登録されていません。')
    const params = new URL(impact.mock.calls[0][0], window.location.origin).searchParams
    expect(Object.fromEntries(params)).toEqual({
      vcenter_id: VC,
      entity_moid: 'vm-10',
      from: harness.calls[0].body.from,
      to: harness.calls[0].body.to,
      at: '2026-03-22T00:10:00Z',
    })
    fireEvent.change(screen.getByLabelText('影響範囲の時点'), { target: { value: 'end' } })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(2))
    const requestedTime = (index: number) => new URL(impact.mock.calls[index][0], window.location.origin).searchParams.get('at')
    expect(requestedTime(1)).toBe(params.get('to'))
    fireEvent.change(screen.getByLabelText('影響範囲の時点'), { target: { value: 'start' } })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(3))
    expect(requestedTime(2)).toBe(params.get('from'))
    fireEvent.change(screen.getByLabelText('影響範囲の時点'), { target: { value: 'default' } })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(4))

    fireEvent.click(screen.getByLabelText('イベント'))
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(impact).toHaveBeenCalledTimes(4)
    await answer(1, emptyViewResponse())
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(5))
    expect(requestedTime(4)).toBe(harness.calls[1].body.from)
  })

  it.each([true, false])('タイムラインが 422 のときは起点または期間の始まりを使う（起点あり: %s）', async (hasAnchor) => {
    setup()
    const impact = vi.fn((url: string) => jsonResponse({ detail: url }, 404))
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', FIXED_IMPACT_HASH + (hasAnchor ? '&anchor=2026-03-22T00:30:00Z' : ''))
    renderTimeline()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    expect(impact).not.toHaveBeenCalled()
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: '出来事が多すぎます。' }, 422))
    })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(1))
    const at = new URL(impact.mock.calls[0][0], window.location.origin).searchParams.get('at')
    expect(at).toBe(hasAnchor ? '2026-03-22T00:30:00.000Z' : '2026-03-22T00:00:00.000Z')
  })

  it.each([429, 500, 503, 'network'])('タイムラインの %s 失敗では影響範囲を取得せず案内を出す', async (failure) => {
    setup()
    const impact = vi.fn(() => jsonResponse({}))
    harness.extra.set('/api/inventory/impact?', impact)
    if (failure === 'network') {
      vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        String(input).endsWith('/api/incident-timeline/view')
          ? Promise.reject(new TypeError('通信できません'))
          : harness.fetchMock(input, init),
      ))
    }
    window.history.replaceState(null, '', FIXED_IMPACT_HASH)
    renderTimeline()
    if (failure !== 'network') {
      const fail = async (index: number) => {
        await waitFor(() => expect(harness.calls).toHaveLength(index + 1))
        await act(async () => {
          harness.calls[index].resolve(jsonResponse({ detail: '読み込みに失敗しました' }, failure, { 'Retry-After': '0' }))
        })
      }
      await fail(0)
      if (failure === 503) await fail(1)
    }
    const section = within(screen.getByRole('region', { name: '影響範囲' }))
    expect(await section.findByRole('status')).toHaveTextContent('タイムラインを読み込めなかったため、影響範囲を出せません')
    expect(impact).not.toHaveBeenCalled()
  })

  it('要求の起点より応答の anchor_utc を優先し、Z のない時刻を UTC として送る', async () => {
    setup()
    const impact = vi.fn((url: string) => jsonResponse({ detail: url }, 404))
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', FIXED_IMPACT_HASH + '&anchor=2026-03-22T00:30:00Z')
    renderTimeline()
    await answer(0, populated({ anchor_utc: '2026-03-22T00:20:00.123456' }))
    expect(harness.calls[0].body.anchor).toBe('2026-03-22T00:30:00.000Z')
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(1))
    expect(new URL(impact.mock.calls[0][0], window.location.origin).searchParams.get('at')).toBe('2026-03-22T00:20:00.123456Z')
  })

  it.each(['start', 'end'])('選択した %s と表示結果を再集計中やタブ移動後も保ち、同じ要求を送らない', async (selection) => {
    setup()
    const impact = vi.fn((url: string) => {
      const at = new URL(url, window.location.origin).searchParams.get('at')
      return jsonResponse({
        target: { moid: 'vm-10', entity_type: 'VirtualMachine', name: 'vm-10' },
        at, status: 'unknown_target', recorded_since: null, last_success_at: null,
        observed_before: null, observed_after: null, groups: [],
      })
    })
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', FIXED_IMPACT_HASH)
    const { rerender } = renderTimeline()
    const select = screen.getByLabelText('影響範囲の時点')
    await answer(0)
    await screen.findByText('この対象の関係の記録がありません。')
    fireEvent.change(select, { target: { value: selection } })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(2))
    const result = await screen.findByText('この対象の関係の記録がありません。')

    fireEvent.click(screen.getByLabelText('イベント'))
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    expect(select).toHaveValue(selection)
    expect(result).toBeInTheDocument()
    expect(impact).toHaveBeenCalledTimes(2)
    await answer(1)
    expect(select).toHaveValue(selection)
    expect(result).toBeInTheDocument()
    expect(impact).toHaveBeenCalledTimes(2)

    const showTab = (active: boolean) => rerender(
      <ThemeProvider><TimeZoneProvider><TimelinePanel onError={onError} active={active} /></TimeZoneProvider></ThemeProvider>,
    )
    window.history.replaceState(null, '', '/#/settings/vcenters')
    showTab(false)
    expect(screen.getByLabelText('影響範囲の時点')).toBe(select)
    window.history.replaceState(null, '', '/#/timeline')
    showTab(true)
    expect(screen.getByLabelText('影響範囲の時点')).toBe(select)
    expect(select).toHaveValue(selection)
    expect(impact).toHaveBeenCalledTimes(2)

    window.history.replaceState(null, '', FIXED_IMPACT_HASH
      .replace('from=2026-03-22T00:00:00Z', 'from=2026-03-21T23:30:00Z')
      .replace('to=2026-03-22T01:00:00Z', 'to=2026-03-22T01:30:00Z'))
    fireEvent(window, new HashChangeEvent('hashchange'))
    await waitFor(() => expect(harness.calls).toHaveLength(3))
    expect(select).toHaveValue(selection)
    expect(impact).toHaveBeenCalledTimes(2)
    await answer(2)
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(3))
    expect(select).toHaveValue(selection)
    expect(new URL(impact.mock.calls[2][0], window.location.origin).searchParams.get('at'))
      .toBe(selection === 'start' ? '2026-03-21T23:30:00.000Z' : '2026-03-22T01:30:00.000Z')
  })

  it.each([
    [/UserLoginSessionEvent/, '2026-03-22T00:50:00Z'],
    [/VmPoweredOffEvent/, '2026-03-22T00:10:00Z'],
  ])('期間の終わりを選んだ後で起点 %s を付けると既定へ戻る', async (item, anchor) => {
    setup()
    const impact = vi.fn((url: string) => jsonResponse({ detail: url }, 404))
    harness.extra.set('/api/inventory/impact?', impact)
    window.history.replaceState(null, '', FIXED_IMPACT_HASH)
    renderTimeline()
    await answer(0)
    const select = screen.getByLabelText('影響範囲の時点')
    await waitFor(() => expect(select).not.toBeDisabled())
    fireEvent.change(select, { target: { value: 'end' } })
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(2))
    fireEvent.click(await rowButton(item))
    fireEvent.click(within(screen.getByRole('list', { name: '出来事の時系列' })).getByRole('button', { name: 'ここを起点にする' }))
    expect(select).toHaveValue('end')
    await answer(1, populated({ anchor_utc: anchor }))
    expect(select).toHaveValue('default')
    await waitFor(() => expect(impact).toHaveBeenCalledTimes(3))
    expect(new URL(impact.mock.calls[2][0], window.location.origin).searchParams.get('at')).toBe(anchor)
  })

  it('開くと「生成」を押さずに自動で読み込み、完了と件数をライブ領域で知らせる', async () => {
    setup()
    renderTimeline()
    expect(screen.queryByRole('button', { name: /生成/ })).not.toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent('読み込み中')
    await answer(0)
    await waitFor(() => expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent('3 件の出来事を表示しています。'))
    expect(screen.getByRole('button', { name: '更新' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '直近 1 時間' })).toHaveAttribute('aria-pressed', 'true')
    expect(window.location.hash).toBe('#/timeline?range=1h')
  })

  it('今の表示の条件と表示タイムゾーンを送り、出力中は両方の形式を無効にする', async () => {
    setup()
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    window.history.replaceState(null, '', timelineEntryHash({ at: '2026-03-22T00:30:00Z', entity: 'vm-a' }))
    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:timeline')
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    try {
      let finish!: (response: Response) => void
      const pending = new Promise<Response>((resolve) => { finish = resolve })
      const fetchExport = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(() => pending)
      vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        return url.startsWith('/api/incident-timeline/export?')
          ? fetchExport(url, init)
          : harness.fetchMock(input, init)
      }))
      renderTimeline()
      await answer(0)
      fireEvent.click(screen.getByLabelText('イベント'))
      await waitFor(() => expect(harness.calls).toHaveLength(2))
      expect(harness.calls[0].body.sources).toContain('event')
      expect(harness.calls[1].body.sources).not.toContain('event')
      const markdown = mainExport().getByRole('button', markdownExport)
      const zip = mainExport().getByRole('button', zipExport)
      fireEvent.click(markdown)
      expect(markdown).toHaveTextContent('出力中…')
      expect(markdown).toBeDisabled()
      expect(zip).toBeDisabled()
      fireEvent.click(markdown)
      fireEvent.click(zip)
      expect(fetchExport).toHaveBeenCalledTimes(1)
      const [path, init] = fetchExport.mock.calls[0]
      expect(path).toBe('/api/incident-timeline/export?format=md&time_zone=Asia%2FTokyo')
      expect(init?.method).toBe('POST')
      const exportBody = JSON.parse(String(init?.body))
      expect(exportBody).toEqual(harness.calls[0].body)
      expect(exportBody).not.toEqual(harness.calls[1].body)
      expect(mainExport().getByRole('status')).toHaveTextContent('出力しています…')
      await act(async () => finish(new Response('# 調査資料', {
        headers: { 'Content-Disposition': 'attachment; filename="timeline-20261124-120000.md"' },
      })))
      expect(mainExport().getByRole('status')).toHaveTextContent('ダウンロードを開始しました')
      expect(createUrl).toHaveBeenCalledWith(expect.any(Blob))
      expect(click.mock.contexts[0]).toHaveProperty('download', 'timeline-20261124-120000.md')
      await vi.advanceTimersByTimeAsync(1)
      expect(revokeUrl).toHaveBeenCalledWith('blob:timeline')
      expect(markdown).toBeEnabled()
    } finally {
      createUrl.mockRestore()
      revokeUrl.mockRestore()
      click.mockRestore()
    }
  })

  it.each([
    [413, 'too large', '出力する結果が大きすぎます。Markdown で出力するか、期間を狭めるか、種別を減らしてください。'],
    [422, [{ loc: ['query', 'time_zone'], msg: '無効です' }], '出力条件を確認してください。query.time_zone: 無効です'],
    [422, [{ loc: ['query', 'time_zone'] }], 'リクエストに失敗しました。時間をおいて再度お試しください。'],
    [422, '', 'リクエストに失敗しました。時間をおいて再度お試しください。'],
    [429, 'rate limited', '短時間に操作が多すぎます。少し待ってから出力してください。'],
    [503, 'busy', 'サーバが混み合っています。しばらく待ってから出力してください。'],
    [409, '別のタブで利用者が切り替わったため、操作を中止しました。', '別のタブで利用者が切り替わったため、操作を中止しました。'],
  ])('調査資料の出力が %s で失敗すると理由を読み上げる（%j）', async (status, detail, message) => {
    setup()
    const fetchExport = vi.fn(() => jsonResponse({ detail }, status, { 'Retry-After': '0' }))
    harness.extra.set('/api/incident-timeline/export?', fetchExport)
    renderTimeline()
    await answer(0)
    fireEvent.click(mainExport().getByRole('button', zipExport))
    await waitFor(() => expect(mainExport().getByRole('status').textContent).toBe(message))
    expect(fetchExport).toHaveBeenCalledTimes(status === 503 ? 2 : 1)
  })

  it('タイムラインの読み込み前と失敗後は調査資料を出力できない', async () => {
    setup()
    renderTimeline()
    expect(mainExport().getByRole('button', markdownExport)).toBeDisabled()
    expect(mainExport().getByRole('button', zipExport)).toBeDisabled()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => harness.calls[0].resolve(jsonResponse({ detail: '読み込み失敗' }, 422)))
    expect(screen.getByRole('alert')).toHaveTextContent('読み込み失敗')
    expect(mainExport().getByRole('button', markdownExport)).toBeDisabled()
    expect(mainExport().getByRole('button', zipExport)).toBeDisabled()
  })

  it('行に時刻・種別・レベル（文字）・対象・タイトル・抜粋・まとめた件数を出す', async () => {
    setup()
    renderTimeline()
    await answer(0)
    const row = (await rowButton(/VmPoweredOffEvent/)).closest('li')!
    expect(within(row).getByText('警告')).toBeInTheDocument()
    expect(within(row).getByText('イベント')).toBeInTheDocument()
    expect(within(row).getByText('vm-a')).toBeInTheDocument()
    expect(within(row).getByText('vm-a was powered off by operator')).toBeInTheDocument()
    expect(within(row).getByText(/×3（最後 .*12:14:00/)).toBeInTheDocument()
    const alertRow = screen.getByRole('button', { name: /CPU 高負荷: 発火/ }).closest('li')!
    expect(within(alertRow).getByText('クリティカル')).toBeInTheDocument()
    expect(within(alertRow).getByText('アラート')).toBeInTheDocument()
  })

  it('時刻は設定したタイムゾーンで表示する（Z の無い時刻も UTC として解釈する）', async () => {
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    setup()
    renderTimeline()
    await answer(0)
    const row = (await rowButton(/VmPoweredOffEvent/)).closest('li')!
    // 00:10 UTC = 09:10 JST
    expect(within(row).getByText(/9:10:00/)).toBeInTheDocument()
    expect(within(row).queryByText(/12:10:00/)).not.toBeInTheDocument()
  })

  it('並び順を切り替えられ、選択は localStorage（旧キー）に覚える', async () => {
    setup()
    renderTimeline()
    await answer(0)
    const titles = () => screen.getAllByRole('listitem').filter((li) => li.classList.contains('timeline-row')).map((li) => li.textContent ?? '')
    expect(titles()[0]).toContain('UserLoginSessionEvent') // 既定は新しい順
    fireEvent.change(screen.getByLabelText('並び順'), { target: { value: 'asc' } })
    expect(titles()[0]).toContain('VmPoweredOffEvent')
    expect(localStorage.getItem('vea.timeline.sort_order')).toBe('asc')
  })

  it('行を開くとメッセージ全文・vCenter・スコア・ガイドが出て、キーボードで開閉できる', async () => {
    setup()
    let guideRequests = 0
    harness.extra.set('/api/event-type-guides', () => {
      guideRequests += 1
      return jsonResponse([
        {
          id: 1,
          event_type: 'VmPoweredOffEvent',
          general_meaning: '電源が切られた',
          typical_causes: '運用操作',
          remediation: '意図したものか確認',
          action_required: false,
        },
      ])
    })
    renderTimeline()
    await answer(0)
    const button = await openFirstRow()
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const region = screen.getByRole('region', { name: /VmPoweredOffEvent の詳細/ })
    expect(region).toHaveTextContent('vm-a was powered off')
    expect(region).toHaveTextContent('by operator')
    expect(region).toHaveTextContent('vc-main')
    expect(region).toHaveTextContent('55')
    await waitFor(() => expect(region).toHaveTextContent('電源が切られた'))
    // ガイドは view ではなく、イベント種別ガイドの一覧（viewer で呼べる）から引く。別の行を開いても取り直さない
    fireEvent.click(await rowButton(/UserLoginSessionEvent/))
    await waitFor(() => expect(screen.getAllByText('この種別のガイドは登録されていません。')).toHaveLength(1))
    expect(guideRequests).toBe(1)
    // 行は <button> なので Tab / Enter / Space で開閉できる。もう一度押すと閉じる
    expect(button.tagName).toBe('BUTTON')
    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
  })

  it('アラートの行はルール名と状態（発火中）を出す', async () => {
    setup()
    renderTimeline()
    await answer(0)
    fireEvent.click(await screen.findByRole('button', { name: /CPU 高負荷: 発火/ }))
    const region = screen.getByRole('region', { name: /CPU 高負荷: 発火 の詳細/ })
    expect(region).toHaveTextContent('ルール名')
    expect(region).toHaveTextContent('CPU 高負荷')
    expect(region).toHaveTextContent('発火中')
    // vCenter が無い行にはイベント・ログで開くリンクを出さない
    expect(within(region).queryByRole('link', { name: 'イベントで開く' })).not.toBeInTheDocument()
    expect(within(region).queryByRole('link', { name: 'ログで開く' })).not.toBeInTheDocument()
  })

  it.each([
    ['event_pattern', false],
    ['metric_threshold', true],
  ])('アラート %s の行に対象名を出し、種別に応じて「この対象で絞る」を出す', async (ruleType, canFilter) => {
    setup()
    renderTimeline()
    const response = populated()
    const items = response.items.map((item) => item.kind === 'alert' ? {
      ...item,
      title: '対象ありのアラート',
      entity_name: 'クラスタ A',
      vcenter_id: VC,
      ref: { ...item.ref, alert_rule_type: ruleType, entity_moid: 'domain-c1' },
    } : item)
    await answer(0, { ...response, items })
    const region = await openRow(/対象ありのアラート/)
    expect(region).toHaveTextContent('クラスタ A')
    expect(Boolean(within(region).queryByRole('button', { name: 'この対象で絞る' }))).toBe(canFilter)
  })

  it('「この対象で絞る」は名前と vCenter と moid を使い、URL から同じ条件で開き直せる', async () => {
    setup()
    const { unmount } = renderTimeline()
    await answer(0)
    await openFirstRow()
    fireEvent.click(screen.getByRole('button', { name: 'この対象で絞る' }))
    await answer(1, populated({ items: [] }))
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC, entity_moid: 'vm-10' })
    expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('vm-a')
    expect(window.location.hash).toContain('entity=vm-a')
    expect(window.location.hash).toContain(`vcenter_id=${VC}`)
    expect(window.location.hash).toContain('entity_moid=vm-10')
    expect(screen.getByText('moid で一致（vm-10）')).toBeInTheDocument()

    unmount()
    renderTimeline()
    await answer(2)
    expect(harness.calls[2].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC, entity_moid: 'vm-10' })
    expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('vm-a')
  })

  it('名前の無い対象のリンクで開き、解除ボタンで moid を外して読み直せる', async () => {
    setup()
    const hash = timelineEntryHash({ at: '2026-03-22T00:30:00Z', vcenterId: VC, entity: null, entityMoid: 'vm-10' })
    window.history.replaceState(null, '', `/${hash}`)
    renderTimeline()
    await answer(0)
    expect(harness.calls[0].body).toMatchObject({ vcenter_id: VC, entity_moid: 'vm-10' })
    expect(harness.calls[0].body).not.toHaveProperty('entity')
    expect(screen.getByRole('searchbox', { name: '対象（ホスト・VM 名）' })).toHaveValue('')
    expect(screen.getByText('moid で一致（vm-10）')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'moid の指定を外す' }))
    await answer(1)
    expect(harness.calls[1].body.vcenter_id).toBe(VC)
    expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
    expect(harness.calls[1].body).not.toHaveProperty('entity')
    expect(window.location.hash).not.toContain('entity_moid')
    expect(screen.queryByText('moid で一致（vm-10）')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'moid の指定を外す' })).not.toBeInTheDocument()
  })

  it('対象欄を編集すると、要求を出す待ち時間の前に moid の印と解除ボタンを隠す', async () => {
    setup()
    window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=vm-a&entity_moid=vm-10`)
    renderTimeline()
    await answer(0)
    const input = screen.getByRole('searchbox', { name: '対象（ホスト・VM 名）' })
    expect(input).toHaveAccessibleDescription('moid で一致（vm-10）')
    expect(screen.getByRole('button', { name: 'moid の指定を外す' })).toBeInTheDocument()
    fireEvent.change(input, { target: { value: 'vm-b' } })
    expect(screen.queryByText('moid で一致（vm-10）')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'moid の指定を外す' })).not.toBeInTheDocument()
    expect(input).not.toHaveAttribute('aria-describedby')
    expect(harness.calls).toHaveLength(1)
    expect(window.location.hash).toContain('entity_moid=vm-10')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(TIMELINE_ENTITY_DEBOUNCE_MS)
    })
    await answer(1)
    expect(harness.calls[1].body.entity).toBe('vm-b')
    expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
  })

  it.each([
    { label: 'vCenter の無い行', vcenter_id: null, entity_moid: 'vm-10' },
    { label: 'moid の無い行', vcenter_id: VC, entity_moid: null },
  ])('$label は名前で絞る', async ({ vcenter_id, entity_moid }) => {
    setup()
    window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=old&entity_moid=vm-99`)
    renderTimeline()
    await answer(0, populated({}, { vcenter_id, ref: { event_id: 1, event_type: 'VmPoweredOffEvent', entity_moid } }))
    await openFirstRow()
    fireEvent.click(screen.getByRole('button', { name: 'この対象で絞る' }))
    await answer(1)
    expect(harness.calls[0].body.entity_moid).toBe('vm-99')
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC })
    expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
    expect(window.location.hash).not.toContain('entity_moid')
  })

  it('「ここを起点にする」で起点が付き、前後のプリセットと「起点を解除」が出る。起点に最も近い行に目印が付く', async () => {
    setup()
    renderTimeline()
    await answer(0)
    expect(screen.queryByRole('button', { name: '起点を解除' })).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /CPU 高負荷: 発火/ }))
    fireEvent.click(screen.getByRole('button', { name: 'ここを起点にする' }))
    expect(harness.calls.length).toBe(2)
    // 結果が来るまでは、古い結果の上に新しい起点の目印を描かない
    expect(screen.queryByText('◆ 起点に最も近い')).not.toBeInTheDocument()
    await answer(1, populated({ anchor_utc: '2026-03-22T00:30:00Z' }))
    expect(harness.calls[1].body.anchor).toBe('2026-03-22T00:30:00.000Z')
    expect(window.location.hash).toContain('anchor=2026-03-22T00%3A30%3A00.000Z')
    expect(screen.getByText('◆ 起点に最も近い')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '起点の前後 1 時間' }))
    await answer(2, populated({ anchor_utc: '2026-03-22T00:30:00Z' }))
    expect(harness.calls[2].body).toMatchObject({ from: '2026-03-21T23:30:00.000Z', to: '2026-03-22T01:30:00.000Z' })
    fireEvent.click(screen.getByRole('button', { name: '起点を解除' }))
    await answer(3)
    expect(harness.calls[3].body.anchor).toBeUndefined()
  })

  it('検知が無いと「検知した障害パターン」の欄を出さない', async () => {
    setup()
    renderTimeline()
    await answer(0, populated({
      highlights: { ...populated().highlights, detected_patterns: [], detected_patterns_total: 0, omitted_patterns: [] },
    }))
    const highlights = await screen.findByRole('region', { name: 'ハイライト' })
    expect(within(highlights).queryByRole('heading', { name: '検知した障害パターン' })).not.toBeInTheDocument()
  })

  it('検知があると既存の 3 つのハイライトと並んで表示し、省いたパターンがなければ定義を取得しない', async () => {
    setup()
    const loadDefinitions = vi.fn(() => jsonResponse([]))
    harness.extra.set('/api/event-patterns', loadDefinitions)
    renderTimeline()
    await answer(0, populated({ highlights: {
      ...populated().highlights, detected_patterns: [DETECTED_PATTERN], detected_patterns_total: 1, omitted_patterns: [],
    } }))
    const highlights = within(await screen.findByRole('region', { name: 'ハイライト' }))
    for (const name of ['最初の兆候', '影響の大きい対象', '初めて出たイベント種別', '検知した障害パターン']) {
      expect(highlights.getByRole('heading', { name })).toBeInTheDocument()
    }
    expect(loadDefinitions).not.toHaveBeenCalled()
  })

  it.each([
    { level: 'critical', levelLabel: 'クリティカル', entity_name: 'esx-pattern', entityLabel: 'esx-pattern' },
    { level: 'error', levelLabel: 'エラー', entity_name: null, entityLabel: 'host-10' },
    { level: 'warning', levelLabel: '警告', entity_name: 'esx-pattern', entityLabel: 'esx-pattern' },
  ] as const)('検知の情報と折りたたんだ説明を出す（$level、$entityLabel）', async ({ level, levelLabel, entity_name, entityLabel }) => {
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    setup()
    renderTimeline()
    await answer(0, populated({ highlights: {
      ...populated().highlights,
      detected_patterns: [{ ...DETECTED_PATTERN, level, entity_name }], detected_patterns_total: 1,
    } }))
    const patterns = await screen.findByRole('region', { name: '検知した障害パターン' })
    const card = within(patterns)
    expect(card.getByText(DETECTED_PATTERN.title)).toBeInTheDocument()
    expect(card.getByText(levelLabel)).toBeInTheDocument()
    expect(card.getByText(entityLabel)).toBeInTheDocument()
    expect(card.getByText('vc-pattern')).toBeInTheDocument()
    expect(card.getByText(/8:55:00.*～.*9:15:00/)).toBeInTheDocument()
    expect(card.getByText('3 件')).toBeInTheDocument()
    expect(card.queryByRole('button', { name: 'この対象で絞る' })).not.toBeInTheDocument()
    const summary = card.getByText('説明')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
    expect(within(details).getByText(DETECTED_PATTERN.description)).toBeVisible()
  })

  it('検知から「ここを起点にする」と、検知の最初の時刻で再集計する', async () => {
    setup()
    window.history.replaceState(null, '', '/#/timeline?from=2026-03-22T00:00:00Z&to=2026-03-22T01:00:00Z')
    renderTimeline()
    await answer(0, populated({ highlights: {
      ...populated().highlights, detected_patterns: [DETECTED_PATTERN], detected_patterns_total: 1,
    } }))
    const patterns = await screen.findByRole('region', { name: '検知した障害パターン' })
    fireEvent.click(within(patterns).getByRole('button', { name: 'ここを起点にする' }))
    await answer(1)
    // API の anchor_time は JSON では anchor という名前で送る。
    expect(harness.calls[1].body.anchor).toBe('2026-03-21T23:55:00.000Z')
    expect(harness.calls[1].body).toMatchObject({ from: harness.calls[0].body.from, to: harness.calls[0].body.to })
  })

  it('起点ボタンをパターン名と対象で区別できる', async () => {
    setup()
    renderTimeline()
    await answer(0, populated({ highlights: {
      ...populated().highlights,
      detected_patterns: [DETECTED_PATTERN, { ...DETECTED_PATTERN, entity_moid: 'host-20', entity_name: null }],
      detected_patterns_total: 2,
    } }))
    const patterns = within(await screen.findByRole('region', { name: '検知した障害パターン' }))
    for (const target of ['esx-pattern', 'host-20']) {
      expect(patterns.getByRole('button', {
        name: 'ここを起点にする', description: `${DETECTED_PATTERN.title} ${target}`,
      })).toBeInTheDocument()
    }
  })

  it('最初と最後が同じ時刻なら 1 回だけ表示する', async () => {
    localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
    setup()
    renderTimeline()
    await answer(0, populated({ highlights: {
      ...populated().highlights,
      detected_patterns: [{ ...DETECTED_PATTERN, last_utc: '2026-03-21T23:55:00Z' }],
      detected_patterns_total: 1,
    } }))
    const patterns = within(await screen.findByRole('region', { name: '検知した障害パターン' }))
    expect(patterns.getByText(/8:55:00/)).not.toHaveTextContent('～')
  })

  it('表示上限を超えた件数と、判定しなかったパターンを知らせる', async () => {
    setup()
    renderTimeline()
    const displayed = Array.from({ length: 20 }, (_, i) => ({ ...DETECTED_PATTERN, entity_moid: `host-${i}` }))
    await answer(0, populated({ highlights: {
      ...populated().highlights,
      detected_patterns: displayed, detected_patterns_total: 23, omitted_patterns: ['apd-timeout'],
    } }))
    const patterns = await screen.findByRole('region', { name: '検知した障害パターン' })
    expect(within(patterns).getByText('ほかに 3 件')).toBeInTheDocument()
    expect(screen.getByText(/件数が多すぎるため判定しなかったパターンがあります/)).toHaveTextContent('apd-timeout')
  })

  it('検知が 0 件でも省いたパターンの名前を出し、更新しても定義を取り直さない', async () => {
    setup()
    const loadDefinitions = vi.fn(() => jsonResponse([{
      id: 'apd-timeout', title: 'APD のタイムアウト', description: 'APD がタイムアウトに達しました。',
      level: 'critical', kind: 'sequence', steps: [
        { event_types: ['esx.problem.storage.apd.start'] }, { event_types: ['esx.problem.storage.apd.timeout'] },
      ], within_minutes: 10, min_count: null,
    }]))
    harness.extra.set('/api/event-patterns', loadDefinitions)
    renderTimeline()
    const response = emptyViewResponse({ highlights: {
      ...emptyViewResponse().highlights, detected_patterns: [], detected_patterns_total: 0, omitted_patterns: ['apd-timeout'],
    } })
    await answer(0, response)
    expect(await screen.findByText(/件数が多すぎるため判定しなかったパターンがあります.*APD のタイムアウト/)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '検知した障害パターン' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '更新' }))
    await answer(1, response)
    expect(loadDefinitions).toHaveBeenCalledTimes(1)
  })

  it('定義の取得に失敗したときは省いたパターンの ID を出す', async () => {
    setup()
    const loadDefinitions = vi.fn(() => jsonResponse({ detail: '取得できません' }, 500))
    harness.extra.set('/api/event-patterns', loadDefinitions)
    renderTimeline()
    await answer(0, populated({ highlights: { ...populated().highlights, omitted_patterns: ['apd-timeout'] } }))
    await waitFor(() => expect(loadDefinitions).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/件数が多すぎるため判定しなかったパターンがあります.*apd-timeout/)).toBeInTheDocument()
  })

  describe('初めて警告以上で出たログの型', () => {
    const card = async () => within(await screen.findByRole('region', { name: '初めて警告以上で出たログの型' }))
    const utcFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'short', timeStyle: 'medium', timeZone: 'UTC' })

    it.each([
      { highlights: { new_log_patterns: null }, message: '判定していません' },
      {
        highlights: { new_log_patterns: [], log_patterns_backfill_pending: true },
        message: 'ログの型を埋め戻し中のため判定していません',
      },
      { highlights: { new_log_patterns: [] }, message: 'この期間に該当する型はありません' },
    ])('判定の状態を表示する（$message）', async ({ highlights, message }) => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse({ highlights }))
      expect((await card()).getByText(message)).toBeInTheDocument()
    })

    it('ログを選んでいない空の結果ではハイライトを表示しない', async () => {
      window.history.replaceState(null, '', '/#/timeline?range=1h&sources=metric')
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      await screen.findByText('この期間に出来事はありません。')
      expect(screen.queryByRole('region', { name: 'ハイライト' })).not.toBeInTheDocument()
    })

    it('慣らし中の出どころと保持期間の注記を表示する', async () => {
      setup()
      renderTimeline()
      const warmingUp = Array.from({ length: 20 }, (_, i) => ({
        vcenter_id: VC,
        vcenter_name: 'vc-warmup',
        source_id: `source-${i}`,
        host: `esx-warmup-${i}`,
        log_kind: 'hostd',
        warmup_ends_at: '2026-03-23T10:00:00Z',
      }))
      await answer(0, emptyViewResponse({ highlights: {
        new_log_patterns: [],
        log_patterns_warming_up: warmingUp,
        log_patterns_warming_up_total: 23,
        new_log_patterns_out_of_retention: true,
      } }))
      const content = await card()
      expect(content.getByText(/慣らし期間中/)).toBeInTheDocument()
      expect(content.getByText(/esx-warmup-0.*vc-warmup.*hostd/)).toHaveTextContent(
        utcFormat.format(new Date('2026-03-23T10:00:00Z')),
      )
      expect(content.getByText('ほかに 3 件')).toBeInTheDocument()
      expect(content.getByText(/ログの保持期間/)).toBeInTheDocument()
      expect(content.getByText('判定できた範囲に該当する型はありません')).toBeInTheDocument()
    })

    it('型を表示し、表示中の結果の期間でログを開き、最初の時刻を起点にできる', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse({ highlights: {
        new_log_patterns: [NEW_LOG_PATTERN_EXAMPLE],
        new_log_patterns_total: 4,
      } }))
      const content = await card()
      expect(content.getByText('ほかに 3 件')).toBeInTheDocument()
      const item = content.getByText('Storage retry took <DURATION>').closest('li')
      expect(item).toHaveTextContent(/vmkernel.*esx01.example.com.*esx02.example.com.*vc-pattern.*3 件/)
      expect(item).toHaveTextContent(utcFormat.format(new Date('2026-03-22T00:10:00Z')))
      expect(item).toHaveTextContent('warning')
      const href = content.getByRole('link', { name: /ログで開く/ }).getAttribute('href')!
      expect(href.split('?')[0]).toBe('#/logs')
      expect(Object.fromEntries(new URLSearchParams(href.split('?')[1]))).toEqual({
        vcenter_id: VC, pattern_key: 'v1:retry',
        from: '2026-03-22T00:00:00Z', to: '2026-03-22T01:00:00Z',
      })
      fireEvent.click(content.getByRole('button', { name: /ここを起点にする/ }))
      await answer(1)
      expect(harness.calls[1].body.anchor).toBe('2026-03-22T00:10:00.000Z')
    })
  })

  describe('構成変更のハイライトと一覧', () => {
    const card = async () => within(await screen.findByRole('region', { name: '構成変更' }))
    const highlights = (overrides: Record<string, unknown> = {}) => ({
      ...populated().highlights,
      config_changes: [CONFIG_CHANGE],
      config_changes_total: 1,
      config_change_counts: { vm_reconfigure: 1 },
      ...overrides,
    })

    it('種類ごとの集計と変更の詳細を障害パターンの隣に表示する', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights({
        detected_patterns: [DETECTED_PATTERN],
        detected_patterns_total: 1,
      }) }))
      const region = await screen.findByRole('region', { name: '構成変更' })
      expect(region.previousElementSibling).toBe(screen.getByRole('region', { name: '検知した障害パターン' }))
      const content = within(region)
      expect(content.getByText(/VM の構成変更.*1 件/)).toBeInTheDocument()
      const change = content.getByText('VM の構成変更').closest('li')
      expect(change).toHaveTextContent('vm-change')
      expect(change).toHaveTextContent('vc-change')
      expect(change).toHaveTextContent('operator-a、operator-b')
      expect(change).toHaveTextContent(/12:08:00.*～.*12:10:00/)
      expect(change).toHaveTextContent('3 件')
      expect(content.queryByText(/全 .* 件のうち/)).not.toBeInTheDocument()
      expect(content.queryByText('古い構成変更は省きました')).not.toBeInTheDocument()
    })

    it('新しい 20 件の対象外も種類別に数え、古い構成変更の省略を別に伝える', async () => {
      setup()
      renderTimeline()
      const changes = Array.from({ length: 20 }, (_, index) => ({
        ...CONFIG_CHANGE, entity_moid: `vm-${index}`, event_ids: [100 + index],
      }))
      await answer(0, populated({ highlights: highlights({
        config_changes: changes,
        config_changes_total: 27,
        config_change_counts: { future_kind: 2, permission: 1, vm_reconfigure: 24 },
        config_changes_truncated: true,
      }) }))
      const content = await card()
      expect(content.getByText(/24 件/)).toHaveTextContent(
        /^VM の構成変更 24 件・権限とロールの変更 1 件・future_kind 2 件$/,
      )
      expect(content.getByText('全 27 件のうち、新しい 20 件を表示しています')).toBeInTheDocument()
      expect(content.getByText('古い構成変更は省きました')).toBeInTheDocument()
    })

    it('項目にはサーバの表示名を使い、省略の案内には実際の表示件数を出す', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights({
        config_changes: [{ ...CONFIG_CHANGE, label: '仮想マシンの再構成' }],
        config_changes_total: 2,
        config_change_counts: { vm_reconfigure: 2 },
      }) }))
      const content = await card()
      expect(content.getByText('仮想マシンの再構成')).toBeInTheDocument()
      expect(content.getByText('VM の構成変更 2 件')).toBeInTheDocument()
      expect(content.getByText('全 2 件のうち、新しい 1 件を表示しています')).toBeInTheDocument()
    })

    it.each([
      [[], null, 'この期間に構成変更はありません'],
      [[], CONFIG_CHANGE.last_utc, '起点までに構成変更はありません'],
      [null, null, '判定していません'],
    ])('変更の詳細が無いときに状態を表示する（%j、起点 %s）', async (config_changes, anchor, message) => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse({
        anchor_utc: anchor,
        highlights: { config_changes },
      }))
      expect((await card()).getByText(message)).toBeInTheDocument()
    })

    it('イベントを種別から外した結果にはカードを表示しない', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights() }))
      await card()
      fireEvent.click(screen.getByLabelText('イベント'))
      await answer(1, emptyViewResponse({ highlights: { config_changes: null } }))
      expect(harness.calls[1].body.sources).not.toContain('event')
      expect(screen.queryByRole('region', { name: '構成変更' })).not.toBeInTheDocument()
    })

    it('変更を指定して最後の時刻を起点にする', async () => {
      setup()
      window.history.replaceState(null, '', '/#/timeline?from=2026-03-22T00:00:00Z&to=2026-03-22T01:00:00Z')
      renderTimeline()
      await answer(0, populated({ highlights: highlights() }))
      fireEvent.click((await card()).getByRole('button', { name: /ここを起点にする.*VM の構成変更.*vm-change.*12:10:00/ }))
      await answer(1)
      expect(harness.calls[1].body.anchor).toBe('2026-03-22T00:10:00.000Z')
    })

    it.each(['vm-20', null])('変更の対象と vCenter で絞る（moid %s）', async (entity_moid) => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights({ config_changes: [{ ...CONFIG_CHANGE, entity_moid }] }) }))
      fireEvent.click((await card()).getByRole('button', { name: /この対象で絞る.*VM の構成変更.*vm-change/ }))
      await answer(1)
      expect(harness.calls[1].body).toMatchObject({ entity: 'vm-change', vcenter_id: VC })
      if (entity_moid) expect(harness.calls[1].body.entity_moid).toBe(entity_moid)
      else expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
    })

    it('終了時刻と対象が同じ変更のボタンを開始時刻と利用者で区別できる', async () => {
      setup()
      renderTimeline()
      const changes = [
        CONFIG_CHANGE,
        { ...CONFIG_CHANGE, first_utc: '2026-03-22T00:09:00Z', user_names: ['operator-c'], event_ids: [1] },
      ]
      await answer(0, populated({ highlights: highlights({ config_changes: changes }) }))
      const content = await card()
      for (const action of ['ここを起点にする', 'この対象で絞る', '一覧の行へ移動']) {
        expect(content.getByRole('button', { name: new RegExp(`^${action}.*operator-a.*12:08:00.*12:10:00`) })).toBeInTheDocument()
        expect(content.getByRole('button', { name: new RegExp(`^${action}.*operator-c.*12:09:00.*12:10:00`) })).toBeInTheDocument()
      }
    })

    it('vCenter が無い変更は対象名で絞り、moid だけの変更には絞り込みを出さない', async () => {
      setup()
      renderTimeline()
      const changes = [
        { ...CONFIG_CHANGE, vcenter_id: null, vcenter_name: null },
        { ...CONFIG_CHANGE, vcenter_id: null, vcenter_name: null, entity_name: null, event_ids: [1] },
      ]
      await answer(0, populated({ highlights: highlights({ config_changes: changes }) }))
      const content = await card()
      expect(content.getByText('vm-20・3 件')).toBeInTheDocument()
      const filter = content.getByRole('button', { name: /この対象で絞る.*vm-change/ })
      expect(content.getAllByRole('button', { name: /^この対象で絞る/ })).toHaveLength(1)
      fireEvent.click(filter)
      await answer(1)
      expect(harness.calls[1].body.entity).toBe('vm-change')
      expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
      expect(harness.calls[1].body).not.toHaveProperty('vcenter_id')
    })

    it('変更に対応する最初の掲載行を開く', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights() }))
      fireEvent.click((await card()).getByRole('button', { name: /一覧の行へ移動.*VM の構成変更.*vm-change/ }))
      expect(await rowButton(/UserLoginSessionEvent/)).toHaveAttribute('aria-expanded', 'true')
      expect(await rowButton(/VmPoweredOffEvent/)).toHaveAttribute('aria-expanded', 'false')
    })

    it('対象も掲載行も無い変更には該当する操作を表示せず、同じ時刻は一度だけ表示する', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({ highlights: highlights({ config_changes: [{
        ...CONFIG_CHANGE, first_utc: CONFIG_CHANGE.last_utc, entity_moid: null, entity_name: null, event_ids: [99],
      }] }) }))
      const content = await card()
      expect(content.queryByRole('button', { name: /この対象で絞る/ })).not.toBeInTheDocument()
      expect(content.queryByRole('button', { name: /一覧の行へ移動/ })).not.toBeInTheDocument()
      expect(content.getByText(/12:10:00/)).not.toHaveTextContent('～')
    })

    it('構成変更の行のバッジを表示し、一覧の上限を注記する', async () => {
      const items = populated().items
      setup()
      renderTimeline()
      await answer(0, populated({
        items: [{ ...items[0], config_change_kind: 'vm_reconfigure' }, ...items.slice(1)],
        total_items: 2,
        config_change_items_total: 3,
        config_change_items_shown: 1,
        config_change_items_truncated: true,
      }))
      const marked = await rowButton(/VmPoweredOffEvent/)
      expect(within(marked).getByText('構成変更')).toBeVisible()
      expect(marked).toHaveAccessibleName(/構成変更/)
      expect(await rowButton(/UserLoginSessionEvent/)).not.toHaveAccessibleName(/構成変更/)
      const list = within(screen.getByRole('region', { name: '時系列リスト' }))
      expect(list.getByRole('note')).toHaveTextContent('構成変更の行は、期間の終わりに近い 1 件だけを一覧に出しています')
    })

    it('通常枠と構成変更枠の両方が上限を超えた場合は、別々の件数で注記を出す', async () => {
      setup()
      renderTimeline()
      await answer(0, populated({
        anchor_utc: CONFIG_CHANGE.last_utc,
        truncated: true,
        total_items: 500,
        config_change_items_total: 3,
        config_change_items_shown: 1,
        config_change_items_truncated: true,
      }))
      const list = within(screen.getByRole('region', { name: '時系列リスト' }))
      const notes = list.getAllByRole('note')
      expect(notes).toHaveLength(2)
      expect(notes[0]).toHaveTextContent('500 件中 2 件を表示しています。期間や対象を絞ってください')
      expect(notes[1]).toHaveTextContent('構成変更の行は、起点に近い 1 件だけを一覧に出しています')
    })
  })

  it('「イベントで開く」「ログで開く」は行の時刻の前後 5 分と vCenter を渡すリンク', async () => {
    setup()
    renderTimeline()
    await answer(0)
    await openFirstRow()
    for (const [name, tab] of [
      ['イベントで開く', 'events'],
      ['ログで開く', 'logs'],
    ] as const) {
      const href = screen.getByRole('link', { name }).getAttribute('href')!
      expect(href.startsWith(`#/${tab}?`)).toBe(true)
      const params = new URLSearchParams(href.split('?')[1])
      expect(params.get('vcenter_id')).toBe(VC)
      expect(params.get('from')).toBe('2026-03-22T00:05:00.000Z')
      // まとめた行（×3、最後は 00:14）は、最初の 5 分前から最後の 5 分後まで
      expect(params.get('to')).toBe('2026-03-22T00:19:00.000Z')
    }
  })

  it('「グラフで開く」は行の時刻の前後 30 分（まとめた行は end_utc の 30 分後まで）と vCenter と起点の目印を渡す', async () => {
    const onOpen = vi.fn()
    setup()
    renderTimeline({ onOpenInMetrics: onOpen })
    await answer(0)
    await openFirstRow()
    const region = screen.getByRole('region', { name: /VmPoweredOffEvent の詳細/ })
    fireEvent.click(within(region).getByRole('button', { name: 'グラフで開く' }))
    expect(onOpen).toHaveBeenLastCalledWith({
      from: '2026-03-21T23:40:00.000Z',
      to: '2026-03-22T00:44:00.000Z',
      vcenterId: VC,
      markerUtc: '2026-03-22T00:10:00.000Z',
      chartEventType: 'VmPoweredOffEvent',
    })
    // 単発の行
    fireEvent.click(await rowButton(/UserLoginSessionEvent/))
    const single = screen.getByRole('region', { name: /UserLoginSessionEvent の詳細/ })
    fireEvent.click(within(single).getByRole('button', { name: 'グラフで開く' }))
    expect(onOpen).toHaveBeenLastCalledWith({
      from: '2026-03-22T00:20:00.000Z',
      to: '2026-03-22T01:20:00.000Z',
      vcenterId: VC,
      markerUtc: '2026-03-22T00:50:00.000Z',
      chartEventType: 'UserLoginSessionEvent',
    })
  })

  it('vCenter の無い行と、開く先が無いときには「グラフで開く」を出さない', async () => {
    const onOpen = vi.fn()
    setup()
    const { unmount } = renderTimeline({ onOpenInMetrics: onOpen })
    await answer(0)
    fireEvent.click(await screen.findByRole('button', { name: /CPU 高負荷: 発火/ }))
    const region = screen.getByRole('region', { name: /CPU 高負荷: 発火 の詳細/ })
    expect(within(region).queryByRole('button', { name: 'グラフで開く' })).not.toBeInTheDocument()
    unmount()
    setup()
    renderTimeline()
    await answer(0)
    await openFirstRow()
    const first = screen.getByRole('region', { name: /VmPoweredOffEvent の詳細/ })
    expect(within(first).queryByRole('button', { name: 'グラフで開く' })).not.toBeInTheDocument()
  })

  it('最初の兆候をクリックすると該当行が開いて強調される。影響の大きい対象のクリックで対象を絞る', async () => {
    setup()
    renderTimeline()
    await answer(0)
    const highlights = await screen.findByRole('region', { name: 'ハイライト' }).catch(() => screen.getByLabelText('ハイライト'))
    fireEvent.click(within(highlights).getByRole('button', { name: /vm-a \/ VmPoweredOffEvent/ }))
    const row = (await rowButton(/VmPoweredOffEvent/)).closest('li')!
    expect(row).toHaveClass('timeline-row--revealed')
    expect(within(highlights).getByText(/初めて出たイベント種別/)).toBeInTheDocument()
    fireEvent.click(within(highlights).getByRole('button', { name: 'vm-a' }))
    await answer(1)
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC, entity_moid: 'vm-10' })
    expect(window.location.hash).toContain('entity_moid=vm-10')
  })

  it('一覧に含まれない最初の兆候はクリックできない旨を出し、データの無い項目は出さない', async () => {
    setup()
    renderTimeline()
    await answer(
      0,
      populated({
        highlights: {
          first_signal: { ...VIEW_RESPONSE_EXAMPLE.items[1], id: 'alert:99', title: '切り捨てられた警告' },
          top_entities: [],
          new_event_types: [],
        },
      }),
    )
    expect(await screen.findByText('切り捨てられた警告')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /切り捨てられた警告/ })).not.toBeInTheDocument()
    expect(screen.getByText(/一覧に含まれていません/)).toBeInTheDocument()
    expect(screen.queryByText('影響の大きい対象')).not.toBeInTheDocument()
    expect(screen.queryByText('初めて出たイベント種別')).not.toBeInTheDocument()
  })

  it('俯瞰グラフ: キーボードで棒を選んで Enter で期間をその範囲に絞り、「絞り込み前の期間に戻す」で戻せる', async () => {
    setup()
    renderTimeline()
    await answer(0)
    const chart = await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
    chart.focus()
    fireEvent.keyDown(chart, { key: 'ArrowRight' }) // 先頭の棒
    fireEvent.keyDown(chart, { key: 'ArrowRight' }) // 2 本目: 00:20〜00:40
    expect(chart.querySelector('.timeline-overview__announce')).toHaveTextContent('2 件')
    fireEvent.keyDown(chart, { key: 'Enter' })
    await answer(1)
    expect(harness.calls[1].body).toMatchObject({ from: '2026-03-22T00:20:00.000Z', to: '2026-03-22T00:40:00.000Z' })
    expect(window.location.hash).toContain('from=2026-03-22T00%3A20%3A00.000Z')
    fireEvent.click(screen.getByRole('button', { name: '絞り込み前の期間に戻す' }))
    await answer(2)
    expect(harness.calls[2].body.from).not.toBe('2026-03-22T00:20:00.000Z')
    expect(window.location.hash).toBe('#/timeline?range=1h')
    expect(screen.queryByRole('button', { name: '絞り込み前の期間に戻す' })).not.toBeInTheDocument()
  })

  it('俯瞰グラフ: Shift + 矢印で範囲を広げられる。最後の棒は期間の終わりで切る', async () => {
    setup()
    renderTimeline()
    await answer(0, populated({ to_utc: '2026-03-22T00:50:00Z' }))
    const chart = await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
    fireEvent.keyDown(chart, { key: 'Home' })
    fireEvent.keyDown(chart, { key: 'ArrowRight', shiftKey: true })
    fireEvent.keyDown(chart, { key: 'ArrowRight', shiftKey: true })
    fireEvent.keyDown(chart, { key: 'Enter' })
    await answer(1)
    expect(harness.calls[1].body).toMatchObject({ from: '2026-03-22T00:00:00.000Z', to: '2026-03-22T00:50:00.000Z' })
  })

  it('起点があれば俯瞰グラフに縦線（ラベル「起点」）が出る', async () => {
    window.history.replaceState(null, '', '/#/timeline?range=1h&anchor=2026-03-22T00:30:00.000Z')
    setup()
    renderTimeline()
    await answer(0, populated({ anchor_utc: '2026-03-22T00:30:00Z' }))
    await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
    const line = document.querySelector('.recharts-reference-line line')!
    // 起点（00:30）は 2 本目の棒（00:20〜00:40）。3 本の棒が 3 等分する描画領域の真ん中あたりに引く
    const x = Number(line.getAttribute('x1'))
    const bars = [...document.querySelectorAll('.recharts-bar-rectangle')].map((el) => el.getBoundingClientRect())
    expect(bars.length).toBeGreaterThan(0)
    expect(x).toBeGreaterThan(32 + (640 - 32 - 8) / 3)
    expect(x).toBeLessThan(32 + (2 * (640 - 32 - 8)) / 3)
  })

  it('truncated のときは「N 件中 M 件を表示しています。期間や対象を絞ってください」を上部に出す', async () => {
    setup()
    renderTimeline()
    await answer(0, populated({ truncated: true, total_items: 1500 }))
    expect(await screen.findByRole('note')).toHaveTextContent('1500 件中 3 件を表示しています。期間や対象を絞ってください')
  })

  it.each([false, true])('追加した構成変更の行を表示件数から除く（truncated=%s）', async (truncated) => {
    setup()
    renderTimeline()
    const base = populated()
    const configChange = { ...base.items[0], id: 'event:50', title: 'vim.event.VmReconfiguredEvent', score: 0 }
    await answer(0, {
      ...base,
      items: [...base.items, configChange],
      total_items: truncated ? 500 : 3,
      truncated,
      config_change_items_shown: 1,
    })

    await screen.findByText(configChange.title)
    expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent(
      truncated ? '500 件中 3 件の出来事を表示しています。' : '3 件の出来事を表示しています。',
    )
    if (truncated) {
      expect(screen.getByRole('note')).toHaveTextContent('500 件中 3 件を表示しています。')
    }
  })

  it('期間内に出来事が無いときは空の状態と「期間を広げる」を出し、押すと期間が広がる', async () => {
    setup()
    renderTimeline()
    await answer(0, emptyViewResponse())
    expect(await screen.findByText('この期間に出来事はありません。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '期間を広げる' }))
    await answer(1, emptyViewResponse())
    const span = (i: number) => Date.parse(String(harness.calls[i].body.to)) - Date.parse(String(harness.calls[i].body.from))
    expect(span(1)).toBe(span(0) * 6) // 1 時間 → 6 時間のプリセット
  })

  it('422 はサーバの detail をそのまま表示する', async () => {
    setup()
    renderTimeline()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: 'イベントの種類が多すぎて集計できません。' }, 422))
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('イベントの種類が多すぎて集計できません。')
  })

  it('422（件数が多すぎる）は、読み直しても同じ結果なので「再読み込み」を出さない。サーバの文言はそのまま出す', async () => {
    setup()
    renderTimeline()
    await waitFor(() => expect(harness.calls.length).toBeGreaterThan(0))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: '対象の出来事が多すぎて集計できません。期間を短くしてください。' }, 422))
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('対象の出来事が多すぎて集計できません。期間を短くしてください。')
    expect(screen.queryByRole('button', { name: '再読み込み' })).not.toBeInTheDocument()
  })

  it('混み合い（503 が続く）は「混み合っています」と分かる表示にする', async () => {
    setup()
    renderTimeline()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({}, 503, { 'Retry-After': '1' }))
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
    await waitFor(() => expect(harness.calls).toHaveLength(2))
    await act(async () => {
      harness.calls[1].resolve(jsonResponse({}, 503))
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('混み合っています')
    // 読み直す意味があるエラーには、今までどおり「再読み込み」を出す
    expect(screen.getByRole('button', { name: '再読み込み' })).toBeInTheDocument()
  })

  it('URL の条件（固定の期間・対象・vCenter）を復元して表示する', async () => {
    window.history.replaceState(
      null,
      '',
      `/#/timeline?from=2026-03-20T00:00:00.000Z&to=2026-03-20T06:00:00.000Z&entity=esx01&vcenter_id=${VC}`,
    )
    setup({ vcenters: [{ id: VC, name: 'vc-main', host: 'h', port: 443, username: 'u', is_enabled: true, created_at: '2026-01-01T00:00:00Z' }] })
    renderTimeline()
    await answer(0, emptyViewResponse())
    expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('esx01')
    await waitFor(() => expect(screen.getByLabelText('vCenter')).toHaveValue(VC))
    expect(harness.calls[0].body).toMatchObject({ from: '2026-03-20T00:00:00.000Z', to: '2026-03-20T06:00:00.000Z', entity: 'esx01' })
    expect(screen.getByRole('button', { name: '直近 1 時間' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('種別（イベント / アラート）を切り替えると sources が変わる。最小スコアは詳細設定に畳まれる', async () => {
    setup()
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByLabelText('イベント'))
    await answer(1, emptyViewResponse())
    expect(harness.calls[1].body.sources).toEqual(['alert', 'metric', 'log'])
    for (const name of ['アラート', 'メトリクス', 'ログ']) fireEvent.click(screen.getByLabelText(name))
    await answer(2, emptyViewResponse())
    await answer(3, emptyViewResponse())
    expect(screen.getByLabelText('ログ')).toBeDisabled() // 最後の 1 つは外せない
    const details = screen.getByText('詳細設定').closest('details')!
    expect(details).not.toHaveAttribute('open')
    const score = within(details).getByLabelText('最小スコア')
    fireEvent.change(score, { target: { value: '40' } })
    fireEvent.blur(score)
    await answer(4, emptyViewResponse())
    expect(harness.calls[4].body.min_score).toBe(40)
  })

  it('詳細設定で構成変更は最小スコアに関係なく表示することを案内する', async () => {
    setup()
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByText('詳細設定'))
    expect(screen.getByText(/構成変更は最小スコアに関係なく表示します。/)).toBeVisible()
  })

  it('「この範囲をチャットで分析」は開く先があるときだけ出し、押すと読み込んだ期間と vCenter だけを渡す', async () => {
    setup()
    const { unmount } = renderTimeline()
    await answer(0, populated())
    await screen.findByRole('list', { name: '出来事の時系列' })
    expect(screen.queryByRole('button', { name: 'この範囲をチャットで分析' })).not.toBeInTheDocument()
    unmount()

    const onOpen = vi.fn()
    setup()
    renderTimeline({ onOpenInChat: onOpen })
    await answer(0, populated())
    fireEvent.change(await screen.findByLabelText('対象（ホスト・VM 名）'), { target: { value: 'vm-a' } })
    const button = screen.getByRole('button', { name: 'この範囲をチャットで分析' })
    // 対象の絞り込みは渡らないことを、操作の説明に書く
    expect(button).toHaveAttribute('title', expect.stringContaining('対象'))
    await waitFor(() => expect(button).toBeEnabled())
    fireEvent.click(button)
    expect(onOpen).toHaveBeenCalledTimes(1)
    const focus = onOpen.mock.calls[0][0] as Record<string, unknown>
    expect(Object.keys(focus).sort()).toEqual(['from', 'fromSavedSnapshot', 'narrowedBy', 'to', 'vcenterId'])
    expect(focus.vcenterId).toBeNull()
    // 絞っていた対象は渡さず、絞っていたことだけ知らせる
    expect(focus.narrowedBy).toEqual(['対象'])
    expect(focus.fromSavedSnapshot).toBe(false)
    expect(Date.parse(String(focus.to))).toBeGreaterThan(Date.parse(String(focus.from)))
  })

  it('名前が空でも moid で絞っているとチャットへの引き継ぎに「対象」と出す', async () => {
    setup()
    window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity_moid=vm-10`)
    const onOpen = vi.fn()
    renderTimeline({ onOpenInChat: onOpen })
    await answer(0)
    fireEvent.click(screen.getByRole('button', { name: 'この範囲をチャットで分析' }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ narrowedBy: ['対象'] }))
  })

  it('チャットへ渡す vCenter は、表示中の結果の要求のもの（条件を変えた直後の読み込み前の値ではない）', async () => {
    const onOpen = vi.fn()
    setup({ vcenters: [{ id: VC, name: 'vc-main' }] })
    renderTimeline({ onOpenInChat: onOpen })
    await answer(0, populated())
    await screen.findByRole('list', { name: '出来事の時系列' })
    fireEvent.change(screen.getByLabelText('vCenter'), { target: { value: VC } })
    await waitFor(() => expect(harness.calls.length).toBeGreaterThan(1))
    fireEvent.click(screen.getByRole('button', { name: 'この範囲をチャットで分析' }))
    expect(onOpen.mock.calls[0][0]).toMatchObject({ vcenterId: null })
  })

  it('スナップショットは既定で閉じており、開くと一覧を読み、選ぶと期間と vCenter が条件へ入って読み直す', async () => {
    const onOpen = vi.fn()
    setup({
      snapshots: [
        {
          snapshot_id: 's1',
          from: '2026-03-10T00:00:00Z',
          to: '2026-03-10T03:00:00Z',
          operator_note: '一次調査メモ',
          timestamp_utc: '2026-03-10T03:30:00Z',
          build_request_payload: { from: '2026-03-10T00:00:00Z', to: '2026-03-10T03:00:00Z', vcenter_id: VC },
          graph_context: { vcenter_id: VC },
        },
      ],
    })
    renderTimeline({ onOpenSnapshotInMetrics: onOpen })
    await answer(0, emptyViewResponse())
    const fetchCalls = () => (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]))
    expect(fetchCalls().some((u) => u.includes('/snapshots/manual'))).toBe(false)
    const toggle = screen.getByRole('button', { name: /スナップショット/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: '一次調査メモ' })).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const item = await screen.findByRole('button', { name: '一次調査メモ' })
    // 開いただけでは条件を上書きしない（先頭を自動で選ばない）
    expect(harness.calls).toHaveLength(1)
    fireEvent.click(item)
    await answer(1, emptyViewResponse())
    expect(harness.calls[1].body).toMatchObject({
      from: '2026-03-10T00:00:00.000Z',
      to: '2026-03-10T03:00:00.000Z',
      vcenter_id: VC,
    })
    expect(window.location.hash).toContain('from=2026-03-10T00%3A00%3A00.000Z')
    fireEvent.click(screen.getByRole('button', { name: 'グラフで開く' }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ snapshot_id: 's1' }))
  })

  it('スナップショットの保存は、表示中の条件を view_request として送り（結果は送らず）、運用メモが必須', async () => {
    let saved: Record<string, unknown> | null = null
    setup()
    harness.extra.set('/api/incident-timeline/snapshots/manual', (_url, init) => {
      saved = JSON.parse(String(init?.body)) as Record<string, unknown>
      return jsonResponse(
        {
          snapshot_id: '00000000-0000-0000-0000-000000000001',
          operator_note: String(saved.operator_note),
          timestamp_utc: '2026-03-22T01:23:45Z',
          build_request_payload: { from: '2026-03-22T00:00:00Z', to: '2026-03-22T01:00:00Z' },
        },
        201,
      )
    })
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByLabelText('ログ'))
    await answer(1, emptyViewResponse())
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    const save = await screen.findByRole('button', { name: 'スナップショットを保存' })
    await waitFor(() => expect(save).toBeDisabled())
    fireEvent.change(screen.getByLabelText('運用メモ（必須）'), { target: { value: '保存テスト' } })
    await waitFor(() => expect(save).toBeEnabled())
    fireEvent.click(save)
    await waitFor(() => expect(saved).not.toBeNull())
    expect(saved).toMatchObject({ operator_note: '保存テスト' })
    expect(saved).toHaveProperty('build_request_payload')
    // 表示中の条件（種別から外したログも含む）をそのまま送る。結果は送らない
    expect(saved!.view_request).toEqual(harness.calls[1].body)
    expect((saved!.view_request as { sources: string[] }).sources).toEqual(['event', 'alert', 'metric'])
    expect(saved!.from).toBe(harness.calls[1].body.from)
    expect(saved).not.toHaveProperty('items')
    expect(saved).not.toHaveProperty('result')
    expect(saved).not.toHaveProperty('result_payload')
  })

  describe('結果つきのスナップショット', () => {
    const SNAPSHOT_ID = '00000000-0000-4000-8000-0000000000aa'
    const viewRequest = {
      from: '2026-03-10T00:00:00Z',
      to: '2026-03-10T03:00:00Z',
      vcenter_id: VC,
      entity: 'esx01',
      anchor: null,
      min_score: 40,
      sources: ['event', 'alert'],
      metric_threshold_cpu_pct: 90,
      metric_threshold_memory_pct: 88,
      metric_threshold_disk_pct: 75,
      metric_threshold_network_pct: 75,
      item_limit: 500,
    }
    const listItem = (overrides: Record<string, unknown> = {}) => ({
      snapshot_id: SNAPSHOT_ID,
      from: '2026-03-10T00:00:00Z',
      to: '2026-03-10T03:00:00Z',
      operator_note: '結果つきメモ',
      timestamp_utc: '2026-03-10T03:30:00Z',
      build_request_payload: { from: '2026-03-10T00:00:00Z', to: '2026-03-10T03:00:00Z', vcenter_id: VC },
      has_result: true,
      view_request: viewRequest,
      ...overrides,
    })
    const detailOf = (overrides: Record<string, unknown> = {}) => ({
      ...listItem(),
      result: populated({ from_utc: '2026-03-10T00:00:00Z', to_utc: '2026-03-10T03:00:00Z' }),
      ...overrides,
    })
    const openSnapshot = async (item: unknown, detail: unknown, impact?: (url: string) => Response) => {
      setup({ snapshots: [item] })
      if (impact) harness.extra.set('/api/inventory/impact?', impact)
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () => jsonResponse(detail))
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
    }

    it('保存した結果を持つスナップショットだけ追加できる', async () => {
      setup({ snapshots: [listItem(), listItem({ snapshot_id: VC, operator_note: '条件のみ', has_result: false })] })
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: 'スナップショット' }))
      const saved = (await screen.findByRole('button', { name: '結果つきメモ' })).closest('li')!
      const conditionsOnly = screen.getByRole('button', { name: '条件のみ' }).closest('li')!
      expect(within(saved).getByRole('button', { name: 'インシデントに追加' })).toBeVisible()
      expect(within(conditionsOnly).queryByRole('button', { name: 'インシデントに追加' })).toBeNull()
    })

    it('保存した結果を表示中は、表示タイムゾーンを付けて保存結果の ZIP を GET する', async () => {
      localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'America/New_York')
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      expect(screen.getByRole('button', { name: /スナップショット「結果つきメモ」.+の調査資料を ZIP で出力/ })).toBeEnabled()
      const snapshotPath = `/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`
      harness.extra.delete(snapshotPath)
      const path = `${snapshotPath}/export`
      const fetchExport = vi.fn<(url: string, init?: RequestInit) => Response>(() => new Response(null, { status: 404 }))
      harness.extra.set(path, fetchExport)
      fireEvent.click(mainExport().getByRole('button', zipExport))
      expect(fetchExport).toHaveBeenCalledWith(`${path}?format=zip&time_zone=America%2FNew_York`, expect.objectContaining({ method: 'GET' }))
      expect(fetchExport.mock.calls[0][1]?.body).toBeUndefined()
      await waitFor(() => expect(mainExport().getByRole('status')).toHaveTextContent('スナップショットが見つかりません'))
      fireEvent.click(screen.getByRole('button', { name: '現在のデータで再集計' }))
      expect(mainExport().getByRole('status')).toBeEmptyDOMElement()
    })

    it('スナップショット一覧で結果が無い行は理由を表示し、両方の出力を無効にする', async () => {
      const note = '調'.repeat(40)
      setup({ snapshots: [listItem({ has_result: false, operator_note: `${note}この続きは省略する` })] })
      renderTimeline()
      await answer(0)
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      const row = within(await within(screen.getByRole('region', { name: 'スナップショット' })).findByRole('listitem'))
      const label = `スナップショット「${note}…」（3/10/26, 3:30:00 AM）の調査資料を`
      expect(row.getByRole('button', { name: `${label} Markdown で出力` })).toBeDisabled()
      expect(row.getByRole('button', { name: `${label} ZIP で出力` })).toBeDisabled()
      expect(row.getByText('結果が保存されていません。')).toBeInTheDocument()
    })

    it('一覧の行から出力中はほかの出力を無効にし、409 の案内を対象の行で読み上げる', async () => {
      setup({ snapshots: [
        listItem(),
        listItem({ snapshot_id: '00000000-0000-4000-8000-0000000000bb', operator_note: '別のメモ' }),
      ] })
      const path = `/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}/export`
      const detail = '結果が保存されていません。開いて再集計してから、今の表示を出力してください。'
      const fetchExport = vi.fn(() => jsonResponse({ detail }, 409, { 'X-VEA-Error-Code': 'snapshot_result_missing' }))
      harness.extra.set(path, fetchExport)
      renderTimeline()
      await answer(0)
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      const markdown = await screen.findByRole('button', { name: /スナップショット「結果つきメモ」.+の調査資料を Markdown で出力/ })
      const otherRow = screen.getByRole('button', { name: /スナップショット「別のメモ」.+の調査資料を Markdown で出力/ })
      const top = mainExport().getByRole('button', zipExport)
      fireEvent.click(markdown)
      expect(markdown).toBeDisabled()
      expect(otherRow).toBeDisabled()
      expect(top).toBeDisabled()
      fireEvent.click(otherRow)
      fireEvent.click(top)
      expect(fetchExport).toHaveBeenCalledTimes(1)
      expect(fetchExport).toHaveBeenCalledWith(`${path}?format=md&time_zone=UTC`, expect.objectContaining({ method: 'GET' }))
      const status = screen.getByRole('status', { name: /スナップショット「結果つきメモ」.+の調査資料の出力状況/ })
      await waitFor(() => expect(status).toHaveTextContent(detail))
      expect(otherRow).toBeEnabled()
      expect(top).toBeEnabled()
    })

    it('開くと保存済みの結果を表示し、「保存時点の内容」と保存日時を注記し、現在のデータは取りに行かない', async () => {
      await openSnapshot(listItem(), detailOf())
      const note = await screen.findByRole('note', { name: '保存時点の内容' })
      expect(note).toHaveTextContent('保存時点の内容')
      expect(note).toHaveTextContent(/保存した日時: .*3\/10\/26.*3:30/)
      expect(await screen.findByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent('3 件の出来事を表示しています。')
      expect(await rowButton(/VmPoweredOffEvent/)).toBeInTheDocument()
      // 条件には保存時の値が入る（URL にも反映）
      expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('esx01')
      expect(window.location.hash).toContain('from=2026-03-10T00%3A00%3A00.000Z')
      // 再集計の要求は出ていない（最初の読み込みの 1 本だけ）
      expect(harness.calls).toHaveLength(1)
    })

    it('保存した結果の対象・起点・期間で影響範囲を取得する', async () => {
      const savedRequest = { ...viewRequest, entity_moid: 'host-20', anchor: '2026-03-10T01:00:00Z' }
      const impact = vi.fn((url: string) => jsonResponse({ detail: url }, 404))
      await openSnapshot(listItem({ view_request: savedRequest }), detailOf({ view_request: savedRequest }), impact)
      await screen.findByText('この vCenter は登録されていません。')
      expect(harness.calls).toHaveLength(1)
      expect(impact).toHaveBeenCalledTimes(1)
      expect(Object.fromEntries(new URL(impact.mock.calls[0][0], window.location.origin).searchParams)).toEqual({
        vcenter_id: VC, entity_moid: 'host-20',
        from: '2026-03-10T00:00:00.000Z', to: '2026-03-10T03:00:00.000Z', at: '2026-03-10T01:00:00.000Z',
      })
    })

    it('検知や構成変更の項目が無い保存済みの結果も表示する', async () => {
      const detail = detailOf()
      expect(detail.result.highlights).not.toHaveProperty('detected_patterns')
      expect(detail.result.highlights).not.toHaveProperty('detected_patterns_total')
      expect(detail.result.highlights).not.toHaveProperty('omitted_patterns')
      await openSnapshot(listItem(), detail)
      await screen.findByRole('note', { name: '保存時点の内容' })
      const highlights = await screen.findByRole('region', { name: 'ハイライト' })
      expect(within(highlights).getByRole('heading', { name: '最初の兆候' })).toBeInTheDocument()
      expect(within(highlights).queryByRole('heading', { name: '検知した障害パターン' })).not.toBeInTheDocument()
      expect(within(within(highlights).getByRole('region', { name: '構成変更' })).getByText('判定していません')).toBeInTheDocument()
      expect(within(highlights).queryByRole('region', { name: '初めて警告以上で出たログの型' })).not.toBeInTheDocument()
      expect(await rowButton(/VmPoweredOffEvent/)).toBeInTheDocument()
    })

    it.each([
      { log_patterns_backfill_pending: true, new_log_patterns: null },
      { log_patterns_backfill_pending: false, new_log_patterns: [] },
    ])('保存結果にログの判定状態があれば種別の選択にかかわらず表示する（%j）', async (highlights) => {
      const detail = detailOf({ result: emptyViewResponse({ highlights }) })
      await openSnapshot(listItem(), detail)
      await screen.findByRole('note', { name: '保存時点の内容' })
      const card = await screen.findByRole('region', { name: '初めて警告以上で出たログの型' })
      expect(card).toHaveTextContent(highlights.log_patterns_backfill_pending ? '埋め戻し中' : 'この期間に該当する型はありません')
    })

    it.each(['host-20', null, undefined])('保存済みの moid（%s）に置き換え、再集計にも使う', async (entity_moid) => {
      window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=vm-a&entity_moid=vm-10`)
      const savedRequest = { ...viewRequest, entity_moid }
      await openSnapshot(listItem({ view_request: savedRequest }), detailOf({ view_request: savedRequest }))
      await screen.findByRole('note', { name: '保存時点の内容' })
      expect(harness.calls[0].body.entity_moid).toBe('vm-10')
      expect(new URLSearchParams(window.location.hash.split('?')[1]).get('entity_moid')).toBe(entity_moid ?? null)
      fireEvent.click(screen.getByRole('button', { name: '現在のデータで再集計' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ entity: 'esx01', vcenter_id: VC })
      expect(harness.calls[1].body.entity_moid).toBe(entity_moid ?? undefined)
    })

    it('「現在のデータで再集計」を押すと、その条件で通常の表示に戻って読み直す', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.click(screen.getByRole('button', { name: '現在のデータで再集計' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({
        from: '2026-03-10T00:00:00.000Z',
        to: '2026-03-10T03:00:00.000Z',
        vcenter_id: VC,
        entity: 'esx01',
        min_score: 40,
        sources: ['event', 'alert'],
        metric_threshold_cpu_pct: 90,
        metric_threshold_memory_pct: 88,
      })
      await waitFor(() => expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument())
    })

    it('条件を変えると、保存済みの内容が黙って入れ替わらず、通常の表示に戻って読み直す', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.click(screen.getByLabelText('アラート'))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body.sources).toEqual(['event'])
      await waitFor(() => expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument())
    })

    it('保存済みの結果を表示している間は、新しいスナップショットを保存できない', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.change(screen.getByLabelText('運用メモ（必須）'), { target: { value: 'x' } })
      expect(screen.getByRole('button', { name: 'スナップショットを保存' })).toBeDisabled()
    })

    it('保存済みの結果の表示中は、保存した期間と vCenter をチャットへ渡す（現在の期間ではない）', async () => {
      const onOpen = vi.fn()
      setup({ snapshots: [listItem()] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () => jsonResponse(detailOf()))
      renderTimeline({ onOpenInChat: onOpen })
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.click(screen.getByRole('button', { name: 'この範囲をチャットで分析' }))
      expect(onOpen).toHaveBeenCalledWith({
        from: '2026-03-10T00:00:00.000Z',
        to: '2026-03-10T03:00:00.000Z',
        vcenterId: VC,
        // 保存した要求で絞っていた対象・種別・最小スコア・しきい値は、渡さずに知らせる
        narrowedBy: ['対象', '種別', '最小スコア', 'しきい値'],
        fromSavedSnapshot: true,
      })
    })

    it('チャットが受け付けない長さ（90 日超）の期間は、押せず理由を示す', async () => {
      const onOpen = vi.fn()
      const long = { from: '2026-01-01T00:00:00Z', to: '2026-06-01T00:00:00Z' }
      setup({ snapshots: [listItem({ ...long, view_request: { ...viewRequest, ...long } })] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        jsonResponse(detailOf({ ...long, view_request: { ...viewRequest, ...long } })),
      )
      renderTimeline({ onOpenInChat: onOpen })
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await screen.findByRole('note', { name: '保存時点の内容' })
      const button = screen.getByRole('button', { name: 'この範囲をチャットで分析' })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', expect.stringContaining('90 日'))
      fireEvent.click(button)
      expect(onOpen).not.toHaveBeenCalled()
    })

    it('has_result が false の旧データは、view_request が無ければ from/to/vcenter_id だけを条件に写して再集計する', async () => {
      setup({ snapshots: [listItem({ has_result: false, view_request: null })] })
      window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=vm-a&entity_moid=vm-10`)
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({
        from: '2026-03-10T00:00:00.000Z',
        to: '2026-03-10T03:00:00.000Z',
        vcenter_id: VC,
      })
      expect(harness.calls[0].body.entity_moid).toBe('vm-10')
      expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
      expect(harness.calls[1].body).not.toHaveProperty('entity')
      expect(window.location.hash).not.toContain('entity_moid')
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
    })

    it.each(['host-20', undefined])('結果の無い旧データは保存済みの moid（%s）を使って再集計する', async (entity_moid) => {
      window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=vm-a&entity_moid=vm-10`)
      setup({ snapshots: [listItem({ has_result: false, view_request: { ...viewRequest, entity_moid } })] })
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[0].body.entity_moid).toBe('vm-10')
      expect(harness.calls[1].body).toMatchObject({ entity: 'esx01', vcenter_id: VC })
      expect(harness.calls[1].body.entity_moid).toBe(entity_moid)
      expect(new URLSearchParams(window.location.hash.split('?')[1]).get('entity_moid')).toBe(entity_moid ?? null)
    })

    it('詳細が結果なし（保存時のスキーマと合わない）で返ったら、view_request の条件で再集計に落ちる', async () => {
      await openSnapshot(listItem(), detailOf({ has_result: false, result: null }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ entity: 'esx01', min_score: 40, sources: ['event', 'alert'] })
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
    })

    it('詳細の取得中に条件を変えたら、後から届いた保存済みの結果で上書きしない', async () => {
      let release: (r: Response) => void = () => {}
      setup({ snapshots: [listItem()] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        new Promise<Response>((res) => {
          release = res
        }) as unknown as Response,
      )
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      fireEvent.click(screen.getByLabelText('アラート'))
      await answer(1, emptyViewResponse())
      await act(async () => {
        release(jsonResponse(detailOf()))
      })
      await act(async () => {
        await new Promise((r) => setTimeout(r, 30))
      })
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
      expect((screen.getByLabelText('アラート') as HTMLInputElement).checked).toBe(false)
      // 選択の表示も、取得に失敗・捨てられたときは元に戻る
      expect(screen.getByRole('button', { name: '結果つきメモ' })).toHaveAttribute('aria-pressed', 'false')
    })

    it('続けて別のスナップショットを選んだら、先の詳細は捨てる', async () => {
      const second = listItem({ snapshot_id: '00000000-0000-4000-8000-0000000000bb', operator_note: '二つ目' })
      let releaseFirst: (r: Response) => void = () => {}
      setup({ snapshots: [listItem(), second] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        new Promise<Response>((res) => {
          releaseFirst = res
        }) as unknown as Response,
      )
      harness.extra.set('/api/incident-timeline/snapshots/manual/00000000-0000-4000-8000-0000000000bb', () =>
        jsonResponse({ ...detailOf(), snapshot_id: second.snapshot_id, operator_note: '二つ目' }),
      )
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      fireEvent.click(await screen.findByRole('button', { name: '二つ目' }))
      expect(await screen.findByRole('note', { name: '保存時点の内容' })).toHaveTextContent('二つ目')
      await act(async () => {
        releaseFirst(jsonResponse(detailOf()))
      })
      await act(async () => {
        await new Promise((r) => setTimeout(r, 30))
      })
      expect(screen.getByRole('note', { name: '保存時点の内容' })).toHaveTextContent('二つ目')
    })

    it('先に選んだ詳細が、後に選んだ詳細より先に届いても、後に選んだほうだけを表示する', async () => {
      const secondId = '00000000-0000-4000-8000-0000000000cc'
      const second = listItem({ snapshot_id: secondId, operator_note: '二つ目' })
      let releaseFirst: (r: Response) => void = () => {}
      let releaseSecond: (r: Response) => void = () => {}
      setup({ snapshots: [listItem(), second] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        new Promise<Response>((res) => {
          releaseFirst = res
        }) as unknown as Response,
      )
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${secondId}`, () =>
        new Promise<Response>((res) => {
          releaseSecond = res
        }) as unknown as Response,
      )
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      const first = await screen.findByRole('button', { name: '結果つきメモ' })
      fireEvent.click(first)
      fireEvent.click(await screen.findByRole('button', { name: '二つ目' }))
      await act(async () => {
        releaseFirst(jsonResponse(detailOf()))
        await new Promise((r) => setTimeout(r, 30))
      })
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
      await act(async () => {
        releaseSecond(jsonResponse({ ...detailOf(), snapshot_id: secondId, operator_note: '二つ目' }))
      })
      expect(await screen.findByRole('note', { name: '保存時点の内容' })).toHaveTextContent('二つ目')
    })

    it('view_request が読めない結果つきスナップショットでも、保存済みの結果を表示でき、再集計は from/to/vcenter_id になる', async () => {
      await openSnapshot(listItem({ view_request: null }), detailOf({ view_request: null }))
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.click(screen.getByRole('button', { name: '現在のデータで再集計' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ from: '2026-03-10T00:00:00.000Z', to: '2026-03-10T03:00:00.000Z', vcenter_id: VC })
    })

    it.each(['host-20', undefined])('保存済みの結果が読めないときは注記し、保存済みの moid（%s）で再集計する', async (entity_moid) => {
      window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}&entity=vm-a&entity_moid=vm-10`)
      const bad = detailOf({
        view_request: { ...viewRequest, entity_moid },
        result: { ...populated(), items: [{ ...populated().items[0], kind: 'k8s' }] },
      })
      await openSnapshot(listItem({ view_request: { ...viewRequest, entity_moid: 'host-99' } }), bad)
      await answer(1, emptyViewResponse())
      expect(harness.calls[0].body.entity_moid).toBe('vm-10')
      expect(harness.calls[1].body).toMatchObject({ entity: 'esx01', vcenter_id: VC })
      expect(harness.calls[1].body.entity_moid).toBe(entity_moid)
      expect(new URLSearchParams(window.location.hash.split('?')[1]).get('entity_moid')).toBe(entity_moid ?? null)
      expect(await screen.findByRole('note', { name: '読み込みの注記' })).toHaveTextContent(
        '保存時点の結果はいまの形式で読めないため、現在のデータで再集計しました',
      )
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
    })

    it('バックエンドが結果を読めなかったとき（has_result が false）も同じ注記を出す', async () => {
      await openSnapshot(listItem(), detailOf({ has_result: false, result: null }))
      await answer(1, emptyViewResponse())
      expect(await screen.findByRole('note', { name: '読み込みの注記' })).toHaveTextContent('いまの形式で読めない')
    })

    it('再集計のあいだ、スナップショットを開く前の結果を新しい条件の下に出さない', async () => {
      setup({ snapshots: [listItem()] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        jsonResponse(detailOf({ result: emptyViewResponse({ from_utc: '2026-03-10T00:00:00Z' }) })),
      )
      renderTimeline()
      await answer(0, populated())
      expect(await rowButton(/VmPoweredOffEvent/)).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await screen.findByRole('note', { name: '保存時点の内容' })
      fireEvent.click(screen.getByRole('button', { name: '現在のデータで再集計' }))
      await waitFor(() => expect(harness.calls.length).toBe(2))
      expect(screen.queryByRole('list', { name: '出来事の時系列' })).not.toBeInTheDocument()
      expect(screen.queryByText(/読み込んだ期間/)).not.toBeInTheDocument()
    })

    it('直近 1 時間から別の期間のスナップショットを開くと、条件バーの期間と入力欄が保存した期間になり、そのまま「適用」しても保存した期間で再集計する', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      expect(screen.getByLabelText('開始日')).toHaveValue('2026-03-10')
      expect(screen.getByLabelText('開始時刻')).toHaveValue('00:00')
      expect(screen.getByLabelText('終了日')).toHaveValue('2026-03-10')
      expect(screen.getByLabelText('終了時刻')).toHaveValue('03:00')
      expect(screen.getByRole('button', { name: '直近 1 時間' })).toHaveAttribute('aria-pressed', 'false')
      expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('esx01')
      expect((screen.getByLabelText('アラート') as HTMLInputElement).checked).toBe(true)
      expect((screen.getByLabelText('ログ') as HTMLInputElement).checked).toBe(false)
      fireEvent.click(screen.getByRole('button', { name: '適用' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({
        from: '2026-03-10T00:00:00.000Z',
        to: '2026-03-10T03:00:00.000Z',
        entity: 'esx01',
        min_score: 40,
        sources: ['event', 'alert'],
      })
    })

    it('保存済みの結果の表示中は「更新」を押せない（再集計は専用のボタン）', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      const refresh = screen.getByRole('button', { name: '更新' })
      expect(refresh).toBeDisabled()
      expect(refresh).toHaveAttribute('title', expect.stringContaining('再集計'))
    })

    it('注記に、保持期間を過ぎた元データの行の出口が空になることと、絞り込みは現在のデータになることを書く', async () => {
      await openSnapshot(listItem(), detailOf())
      const note = await screen.findByRole('note', { name: '保存時点の内容' })
      expect(note).toHaveTextContent('保持期間')
      expect(note).toHaveTextContent('イベントで開く')
      expect(note).toHaveTextContent('この対象で絞る')
    })

    it('保存済みの結果の表示中に URL（入口リンク）が変わったら、通常の表示に戻って読み直す', async () => {
      await openSnapshot(listItem(), detailOf())
      await screen.findByRole('note', { name: '保存時点の内容' })
      await act(async () => {
        window.history.replaceState(null, '', '/#/timeline?range=6h&entity=other')
        window.dispatchEvent(new HashChangeEvent('hashchange'))
      })
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ entity: 'other' })
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
    })

    it('保存した日時はサーバの created_at を使い、一覧にも出す', async () => {
      await openSnapshot(
        listItem({ created_at: '2026-03-11T05:06:07Z' }),
        detailOf({ created_at: '2026-03-11T05:06:07Z' }),
      )
      expect(await screen.findByRole('note', { name: '保存時点の内容' })).toHaveTextContent(/3\/11\/26.*5:06/)
      expect(screen.getByText(/3\/11\/26.*5:06/, { selector: '.timeline-snapshots__time' })).toBeInTheDocument()
    })

    it('詳細の取得に失敗したらエラーを出し、表示は変えない', async () => {
      onError.mockClear()
      setup({ snapshots: [listItem()] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () =>
        jsonResponse({ detail: 'boom' }, 500),
      )
      renderTimeline()
      await answer(0, populated())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
      await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.any(String)))
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
      expect(harness.calls).toHaveLength(1)
      expect(screen.getByRole('button', { name: '結果つきメモ' })).toHaveAttribute('aria-pressed', 'false')
    })
  })

  it('URL が読めない条件に変わったら、保存ボタンは無効になる（直前の条件を保存し続けない）', async () => {
    setup()
    renderTimeline()
    await answer(0, populated())
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    fireEvent.change(await screen.findByLabelText('運用メモ（必須）'), { target: { value: 'memo' } })
    const save = screen.getByRole('button', { name: 'スナップショットを保存' })
    await waitFor(() => expect(save).toBeEnabled())
    await act(async () => {
      window.history.replaceState(null, '', '/#/timeline?range=6h&vcenter_id=abc')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await screen.findByRole('alert')
    expect(save).toBeDisabled()
  })

  it('保存が 413（結果が大きすぎる）のときは、期間を狭めるよう案内する専用の文言を出す', async () => {
    onError.mockClear()
    setup()
    harness.extra.set('/api/incident-timeline/snapshots/manual', () => jsonResponse({ detail: '大きすぎ' }, 413))
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    fireEvent.change(await screen.findByLabelText('運用メモ（必須）'), { target: { value: 'memo' } })
    const save = screen.getByRole('button', { name: 'スナップショットを保存' })
    await waitFor(() => expect(save).toBeEnabled())
    fireEvent.click(save)
    await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining('期間を狭めるか')))
  })

  it('バックエンドが返す形（graph_context の metric_key などが null）の一覧でも、一覧が表示される', async () => {
    setup({
      snapshots: [
        {
          snapshot_id: '00000000-0000-4000-8000-0000000000dd',
          from: '2026-03-22T00:00:00Z',
          to: '2026-03-22T02:00:00Z',
          operator_note: '実機の形',
          timestamp_utc: '2026-03-22T03:00:00Z',
          build_request_payload: { from: '2026-03-22T00:00:00Z', to: '2026-03-22T02:00:00Z', vcenter_id: null },
          snapshot_kind: 'manual',
          trigger_id: null,
          trigger_evidence: null,
          graph_context: {
            metric_key: null,
            chart_event_type: null,
            marker_timestamp_utc: '2026-03-22T03:00:00Z',
            vcenter_id: null,
            captured_range: { from: '2026-03-22T00:00:00Z', to: '2026-03-22T02:00:00Z' },
          },
          has_result: false,
          view_request: null,
          created_at: '2026-03-22T03:00:01Z',
        },
      ],
    })
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    expect(await screen.findByRole('button', { name: '実機の形' })).toBeInTheDocument()
    expect(screen.queryByText('読み込み中…')).not.toBeInTheDocument()
  })

  it('一覧の応答が想定の形でないときは、zod の生の JSON ではなく短い文言を出し、「読み込み中…」のままにしない', async () => {
    onError.mockClear()
    setup({ snapshots: [{ snapshot_id: 'bad' }] })
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    await waitFor(() => expect(onError).toHaveBeenCalled())
    const message = String(onError.mock.calls[0][0])
    expect(message).toContain('スナップショットの一覧を読み込めませんでした')
    expect(message).not.toContain('"path"')
    expect(screen.queryByText('読み込み中…')).not.toBeInTheDocument()
    expect(screen.getByText(/一覧を読み込めませんでした/)).toBeInTheDocument()
  })

  it('旧画面の「タイムラインを生成」ボタンは無い', async () => {
    setup()
    renderTimeline()
    await answer(0, emptyViewResponse())
    expect(screen.queryByText('タイムラインを生成')).not.toBeInTheDocument()
  })

  it('読み込んだ期間（開始〜終了とタイムゾーン）を常に出す', async () => {
    setup()
    renderTimeline()
    expect(screen.queryByText(/読み込んだ期間/)).not.toBeInTheDocument()
    await answer(0)
    const line = await screen.findByText(/読み込んだ期間/)
    expect(line).toHaveTextContent('（UTC）')
    expect(line.textContent).toMatch(/～/)
  })

  it('一覧に無い vCenter の ID は「全て」と見せず、不明な vCenter として選択肢に出す', async () => {
    window.history.replaceState(null, '', `/#/timeline?range=1h&vcenter_id=${VC}`)
    setup({ vcenters: [] })
    renderTimeline()
    await answer(0, emptyViewResponse())
    const select = screen.getByLabelText('vCenter') as HTMLSelectElement
    await waitFor(() => expect(select.value).toBe(VC))
    expect(within(select).getByRole('option', { name: /不明な vCenter/ })).toBeInTheDocument()
  })

  it('URL の vcenter_id が UUID でなければ読み込まず理由を出し、URL はそのまま', async () => {
    window.history.replaceState(null, '', '/#/timeline?range=6h&vcenter_id=abc')
    setup()
    renderTimeline()
    expect(await screen.findByRole('alert')).toHaveTextContent('UUID')
    expect(harness.calls).toHaveLength(0)
    expect(window.location.hash).toBe('#/timeline?range=6h&vcenter_id=abc')
  })

  it('逆順の期間の URL は理由を出し、「直近 1 時間」に黙って置き換えない', async () => {
    const hash = '#/timeline?from=2026-03-22T02:00:00Z&to=2026-03-22T01:00:00Z'
    window.history.replaceState(null, '', `/${hash}`)
    setup()
    renderTimeline()
    expect(await screen.findByRole('alert')).toHaveTextContent('開始')
    expect(harness.calls).toHaveLength(0)
    expect(window.location.hash).toBe(hash)
  })

  it('期間の入力欄は「適用」で確定する（入力しただけでは読み込まない）', async () => {
    setup()
    renderTimeline()
    await answer(0, emptyViewResponse())
    fireEvent.change(screen.getByLabelText('開始日'), { target: { value: '2026-03-20' } })
    fireEvent.change(screen.getByLabelText('開始時刻'), { target: { value: '10:00' } })
    fireEvent.change(screen.getByLabelText('終了日'), { target: { value: '2026-03-20' } })
    fireEvent.change(screen.getByLabelText('終了時刻'), { target: { value: '11:00' } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(harness.calls).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '適用' }))
    await answer(1, emptyViewResponse())
    expect(harness.calls[1].body).toMatchObject({ from: '2026-03-20T10:00:00.000Z', to: '2026-03-20T11:00:59.000Z' })
    expect(window.location.hash).toContain('from=2026-03-20T10%3A00%3A00.000Z')
  })

  it('429 は「短時間に操作が多すぎます」と出し、自動では再試行しない', async () => {
    setup()
    renderTimeline()
    await waitFor(() => expect(harness.calls).toHaveLength(1))
    await act(async () => {
      harness.calls[0].resolve(jsonResponse({ detail: 'Too many requests' }, 429))
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('短時間に操作が多すぎます')
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12_000)
    })
    expect(harness.calls).toHaveLength(1)
  })

  it('俯瞰グラフは application ロールで、操作方法の説明（aria-describedby）を持つ', async () => {
    setup()
    renderTimeline()
    await answer(0)
    const chart = await screen.findByRole('application', { name: '件数の俯瞰グラフ' })
    const helpId = chart.getAttribute('aria-describedby')!
    expect(document.getElementById(helpId)).toHaveTextContent('矢印')
    expect(chart).toHaveAttribute('tabindex', '0')
  })

  it('バケットの数が減る応答に差し替わっても、キーボードの選択が残って描画が落ちない（End → Enter の後）', async () => {
    setup()
    renderTimeline()
    const many = Array.from({ length: 72 }, (_, i) =>
      bucket(new Date(Date.parse('2026-03-22T00:00:00Z') + i * 300_000).toISOString(), 1, 0),
    )
    await answer(0, populated({ bucket_seconds: 300, to_utc: '2026-03-22T06:00:00Z', overview: many }))
    const chart = await screen.findByRole('application', { name: '件数の俯瞰グラフ' })
    chart.focus()
    fireEvent.keyDown(chart, { key: 'End' })
    fireEvent.keyDown(chart, { key: 'Enter' }) // 最後の 5 分間に絞る
    const fewer = Array.from({ length: 60 }, (_, i) =>
      bucket(new Date(Date.parse('2026-03-22T05:55:00Z') + i * 5_000).toISOString(), 0, 0),
    )
    await answer(
      1,
      populated({ bucket_seconds: 5, from_utc: '2026-03-22T05:55:00Z', to_utc: '2026-03-22T06:00:00Z', overview: fewer }),
    )
    // 添字 71 は存在しない。例外にならず、選択は解除されている
    const after = await screen.findByRole('application', { name: '件数の俯瞰グラフ' })
    expect(after.querySelector('.timeline-overview__announce')).toHaveTextContent('')
    expect(document.querySelector('.recharts-reference-area')).toBeNull()
    // 続けて矢印キーで選び直せる（先頭の棒から）
    fireEvent.keyDown(after, { key: 'ArrowRight' })
    expect(after.querySelector('.timeline-overview__announce')).toHaveTextContent('Enter で期間をこの範囲に絞ります')
    fireEvent.keyDown(after, { key: 'Enter' })
    await answer(2)
    expect(harness.calls[2].body).toMatchObject({ from: '2026-03-22T05:55:00.000Z', to: '2026-03-22T05:55:05.000Z' })
  })

  // ---- メトリクスの超過区間とエラーログ -------------------------------------------------

  const METRIC_TITLE = /CPU 使用率が閾値（80%）を超過/
  const LOG_TITLE = /vmkernel/

  function bucketFull(start: string, extra: Partial<ReturnType<typeof bucket>> = {}) {
    return { ...bucket(start), ...extra }
  }

  /** イベント 1 行・メトリクス 1 行・ログ 1 行。 */
  function withMetricsAndLogs(overrides: Record<string, unknown> = {}) {
    const items = [
      {
        ...METRIC_ITEM_EXAMPLE,
      },
      {
        ...LOG_ITEM_EXAMPLE,
      },
      populated().items[0],
    ]
    return populated({
      items,
      total_items: 3,
      overview: [
        bucketFull('2026-03-22T00:00:00Z', { event_total: 1, metric_breach: 1 }),
        bucketFull('2026-03-22T00:20:00Z', { metric_breach: 2, log_error: 3 }),
        bucketFull('2026-03-22T00:40:00Z', { log_error: 5000 }),
      ],
      highlights: { first_signal: items[0], top_entities: [], new_event_types: [] },
      ...overrides,
    })
  }

  const openRow = async (name: RegExp) => {
    fireEvent.click(await rowButton(name))
    return screen.getByRole('region', { name: new RegExp(`${name.source} の詳細`) })
  }

  describe('条件バー: 種別としきい値', () => {
    it('種別は「イベント」「アラート」「メトリクス」「ログ」の 4 つで、既定はすべて選ばれていて URL に出ない', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      for (const name of ['イベント', 'アラート', 'メトリクス', 'ログ']) {
        expect(screen.getByLabelText(name)).toBeChecked()
      }
      expect(harness.calls[0].body.sources).toEqual(['event', 'alert', 'metric', 'log'])
      expect(window.location.hash).toBe('#/timeline?range=1h')
    })

    it('メトリクスとログの切り替えは要求の本文と URL に反映される', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByLabelText('ログ'))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body.sources).toEqual(['event', 'alert', 'metric'])
      expect(window.location.hash).toBe('#/timeline?range=1h&sources=event%2Calert%2Cmetric')
    })

    it('URL の種別から復元する', async () => {
      window.history.replaceState(null, '', '/#/timeline?range=1h&sources=metric,log')
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      expect(screen.getByLabelText('イベント')).not.toBeChecked()
      expect(screen.getByLabelText('メトリクス')).toBeChecked()
      expect(screen.getByLabelText('ログ')).toBeChecked()
    })

    it('詳細設定に CPU・メモリのしきい値（既定 80・85）があり、ディスクとネットワークの欄は無い', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      const details = screen.getByText('詳細設定').closest('details')!
      expect(within(details).getByLabelText('CPU 使用率のしきい値（%）')).toHaveValue(80)
      expect(within(details).getByLabelText('メモリ使用率のしきい値（%）')).toHaveValue(85)
      expect(within(details).queryByLabelText(/ディスク/)).not.toBeInTheDocument()
      expect(within(details).queryByLabelText(/ネットワーク/)).not.toBeInTheDocument()
      expect(details).toHaveTextContent('ディスクとネットワークは対象外')
    })

    it('しきい値は Enter かフォーカスを外したときに確定し、要求の本文と URL に反映される（既定のときは URL に出ない）', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      const cpu = screen.getByLabelText('CPU 使用率のしきい値（%）')
      fireEvent.change(cpu, { target: { value: '9' } })
      fireEvent.change(cpu, { target: { value: '90' } })
      expect(harness.calls).toHaveLength(1) // 入力途中では読み込まない
      fireEvent.keyDown(cpu, { key: 'Enter' })
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ metric_threshold_cpu_pct: 90, metric_threshold_memory_pct: 85 })
      expect(window.location.hash).toBe('#/timeline?range=1h&cpu_threshold=90')
      const memory = screen.getByLabelText('メモリ使用率のしきい値（%）')
      fireEvent.change(memory, { target: { value: '70.5' } })
      fireEvent.blur(memory)
      await answer(2, emptyViewResponse())
      expect(harness.calls[2].body).toMatchObject({ metric_threshold_cpu_pct: 90, metric_threshold_memory_pct: 70.5 })
      fireEvent.change(cpu, { target: { value: '80' } })
      fireEvent.blur(cpu)
      await answer(3, emptyViewResponse())
      expect(window.location.hash).toBe('#/timeline?range=1h&memory_threshold=70.5')
    })

    it.each([
      ['abc', ''], // type=number は数値でない文字を空にする
      ['', ''],
      ['150', '0〜100'],
      ['-1', '0〜100'],
    ])('しきい値に %s を入れて確定すると、読み込まずに理由を示す', async (value, reason) => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      const cpu = screen.getByLabelText('CPU 使用率のしきい値（%）')
      fireEvent.change(cpu, { target: { value } })
      fireEvent.blur(cpu)
      const alert = await screen.findByText(/CPU 使用率のしきい値は/)
      expect(alert).toHaveTextContent(reason || '0〜100 の数値')
      expect(cpu).toHaveAttribute('aria-invalid', 'true')
      expect(harness.calls).toHaveLength(1)
      // 直すと理由は消え、確定できる
      fireEvent.change(cpu, { target: { value: '88' } })
      expect(screen.queryByText(/CPU 使用率のしきい値は/)).not.toBeInTheDocument()
      fireEvent.keyDown(cpu, { key: 'Enter' })
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body.metric_threshold_cpu_pct).toBe(88)
    })

    it('詳細設定の要約のしきい値は、小数 2 桁まで・末尾の 0 を書かない規則で書く', async () => {
      window.history.replaceState(null, '', '/#/timeline?range=1h&cpu_threshold=80.123&memory_threshold=70.5')
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      const summary = screen.getByText('詳細設定').closest('summary')!
      expect(summary).toHaveTextContent('CPU 80.12%・メモリ 70.5%')
    })

    it('URL のしきい値を復元して欄に出す', async () => {
      window.history.replaceState(null, '', '/#/timeline?range=1h&memory_threshold=60')
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      expect(screen.getByLabelText('メモリ使用率のしきい値（%）')).toHaveValue(60)
      expect(harness.calls[0].body.metric_threshold_memory_pct).toBe(60)
    })
  })

  describe('メトリクスの超過区間の行', () => {
    it('種別・レベル（文字）・対象・タイトルと、区間（から〜まで）・継続時間・ピーク・しきい値・サンプル数を行の中で読める', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(within(row).getByText('メトリクス')).toBeInTheDocument()
      expect(within(row).getByText('警告')).toBeInTheDocument()
      expect(within(row).getByText('esx01')).toBeInTheDocument()
      const interval = row.querySelector('.timeline-row__interval')!
      expect(interval).toHaveTextContent(/12:05:00.* から .*12:15:00.* まで（継続 10 分）/)
      const peak = row.querySelector('.timeline-row__peak')!
      expect(peak).toHaveTextContent(/ピーク 92\.5%（.*12:10:00.*）/)
      expect(peak).toHaveTextContent('しきい値 80%')
      expect(peak).toHaveTextContent('サンプル 3 件')
      // 構造化した値があるときは、detail をそのまま重ねて出さない
      expect(row).not.toHaveTextContent('ピーク 92.5%、サンプル 3 件')
    })

    it('ピークの時刻は設定したタイムゾーンで表示する', async () => {
      localStorage.setItem(DISPLAY_TIME_ZONE_STORAGE_KEY, 'Asia/Tokyo')
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(row.querySelector('.timeline-row__peak')).toHaveTextContent(/9:10:00/)
      expect(row.querySelector('.timeline-row__interval')).toHaveTextContent(/9:05:00.* から .*9:15:00/)
    })

    it('end_utc が無い単発のサンプルは「単発」と分かる表示にする（継続時間は出さない）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ items: [{ ...METRIC_ITEM_EXAMPLE, end_utc: null }], total_items: 1 }))
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      const interval = row.querySelector('.timeline-row__interval')!
      expect(interval).toHaveTextContent('単発')
      expect(interval).not.toHaveTextContent('継続')
      expect(interval).not.toHaveTextContent('から')
    })

    it('continues_from_before が真なら「期間の開始前から」と書き、継続時間は「N 分以上」にする', async () => {
      setup()
      renderTimeline()
      const item = { ...METRIC_ITEM_EXAMPLE, ref: { ...METRIC_ITEM_EXAMPLE.ref, continues_from_before: true } }
      await answer(0, withMetricsAndLogs({ items: [item], total_items: 1 }))
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(row.querySelector('.timeline-row__interval')).toHaveTextContent(/期間の開始前から .*12:15:00.* まで（継続 10 分以上）/)
    })

    it('continues_after が真なら、終わりを言い切らず「期間の終わりでも継続中」と書く。単発でも「単発」と言わない', async () => {
      setup()
      renderTimeline()
      const ref = { ...METRIC_ITEM_EXAMPLE.ref, continues_after: true }
      await answer(
        0,
        withMetricsAndLogs({
          items: [
            { ...METRIC_ITEM_EXAMPLE, ref },
            { ...METRIC_ITEM_EXAMPLE, id: 'metric:2', end_utc: null, title: '単発の続き', ref },
          ],
          total_items: 2,
        }),
      )
      const long = (await rowButton(METRIC_TITLE)).closest('li')!.querySelector('.timeline-row__interval')!
      expect(long).toHaveTextContent('期間の終わり（')
      expect(long).toHaveTextContent('でも継続中。継続 10 分以上）')
      expect(long).not.toHaveTextContent('まで')
      const single = (await rowButton(/単発の続き/)).closest('li')!.querySelector('.timeline-row__interval')!
      expect(single).toHaveTextContent('期間の終わりでも継続中')
      expect(single).not.toHaveTextContent('単発（')
    })

    it('数値は小数 2 桁まで・末尾の 0 を書かない規則で表示する', async () => {
      setup()
      renderTimeline()
      const ref = { ...METRIC_ITEM_EXAMPLE.ref, peak_value: 82.55, threshold_pct: 82.5 }
      await answer(0, withMetricsAndLogs({ items: [{ ...METRIC_ITEM_EXAMPLE, ref }], total_items: 1 }))
      const peak = (await rowButton(METRIC_TITLE)).closest('li')!.querySelector('.timeline-row__peak')!
      expect(peak).toHaveTextContent('ピーク 82.55%')
      expect(peak).toHaveTextContent('しきい値 82.5%')
    })

    it('期間の端で続いていなければ、その表示は出さない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await rowButton(METRIC_TITLE)
      expect(document.body).not.toHaveTextContent('期間の開始前から')
      expect(document.body).not.toHaveTextContent('でも継続中')
    })

    it('構造化した値（ref の追加項目）が無い応答では detail をそのまま出し、しきい値などは出さない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ items: [METRIC_ITEM_LEGACY_EXAMPLE], total_items: 1 }))
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(within(row).getByText('ピーク 92.5%、サンプル 3 件')).toBeInTheDocument()
      expect(row.querySelector('.timeline-row__peak')).toBeNull()
      expect(row).not.toHaveTextContent('しきい値')
      // 区間は timestamp / end_utc から出せる
      expect(row.querySelector('.timeline-row__interval')).toHaveTextContent('継続 10 分')
    })

    it('区間の表示は狭い幅でも折り返せる（折り返し可能なクラスで包む）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(row.querySelector('.timeline-row__interval')).toBeInTheDocument()
      expect(row.querySelector('.timeline-row__summary')).toBeInTheDocument()
    })

    it('操作は「この対象で絞る」「ここを起点にする」「イベントで開く」「グラフで開く」。ログで開く・ガイドは出さない', async () => {
      setup()
      renderTimeline({ onOpenInMetrics: vi.fn() })
      await answer(0, withMetricsAndLogs())
      const region = await openRow(METRIC_TITLE)
      expect(within(region).getByRole('button', { name: 'この対象で絞る' })).toBeInTheDocument()
      expect(within(region).getByRole('button', { name: 'ここを起点にする' })).toBeInTheDocument()
      expect(within(region).getByRole('link', { name: 'イベントで開く' })).toBeInTheDocument()
      expect(within(region).getByRole('button', { name: 'グラフで開く' })).toBeInTheDocument()
      expect(within(region).queryByRole('link', { name: 'ログで開く' })).not.toBeInTheDocument()
      expect(region.querySelector('.timeline-guide')).toBeNull()
    })

    it('「グラフで開く」は区間の開始の 30 分前から終了の 30 分後まで、指標、ピークの時刻の縦線を渡す', async () => {
      const onOpen = vi.fn()
      setup()
      renderTimeline({ onOpenInMetrics: onOpen })
      await answer(0, withMetricsAndLogs())
      const region = await openRow(METRIC_TITLE)
      fireEvent.click(within(region).getByRole('button', { name: 'グラフで開く' }))
      expect(onOpen).toHaveBeenLastCalledWith({
        from: '2026-03-21T23:35:00.000Z',
        to: '2026-03-22T00:45:00.000Z',
        vcenterId: VC,
        markerUtc: '2026-03-22T00:10:00.000Z',
        metricKey: 'host.cpu.usage_pct',
      })
    })

    it('展開すると、指標・しきい値・ピーク・サンプル数・区間の長さを出す', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(METRIC_TITLE)
      expect(region).toHaveTextContent('host.cpu.usage_pct')
      expect(region).toHaveTextContent('80%')
      expect(region).toHaveTextContent('92.5%')
      expect(region).toHaveTextContent('3 件')
      expect(region).toHaveTextContent('10 分')
    })

    it('「この対象で絞る」は対象と vCenter を条件に入れる', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(METRIC_TITLE)
      fireEvent.click(within(region).getByRole('button', { name: 'この対象で絞る' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ entity: 'esx01', vcenter_id: VC })
    })
  })

  describe('エラーログの行', () => {
    it('種別・レベル（文字）・出どころ（タイトル）・メッセージの抜粋・まとめた件数（×N と最後の時刻）を出す', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const row = (await rowButton(LOG_TITLE)).closest('li')!
      expect(within(row).getByText('ログ', { selector: '.timeline-row__kind' })).toBeInTheDocument()
      expect(within(row).getByText('警告')).toBeInTheDocument()
      expect(within(row).getByText(/×2（最後 .*1:01:00/)).toBeInTheDocument()
      expect(within(row).getByText('vmhba0: timeout retrying command')).toBeInTheDocument()
    })

    it('タイトルが対象名で始まるときは、行の中ではログの種類だけを出す（ホスト名を 2 回出さない）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const row = (await rowButton(LOG_TITLE)).closest('li')!
      expect(row.querySelector('.timeline-row__entity')).toHaveTextContent('esx01.example.com')
      expect(row.querySelector('.timeline-row__title')?.textContent).toBe('vmkernel')
      expect(row.textContent!.match(/esx01\.example\.com/g)).toHaveLength(1)
      // 詳細領域の名前は、省かない完全なタイトル
      fireEvent.click(row.querySelector('button')!)
      expect(screen.getByRole('region', { name: 'esx01.example.com vmkernel の詳細' })).toBeInTheDocument()
    })

    it('タイトルが対象名で始まらないときは、タイトルをそのまま出す', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ items: [{ ...LOG_ITEM_EXAMPLE, title: 'other-host syslog' }], total_items: 1 }))
      const row = (await rowButton(/syslog/)).closest('li')!
      expect(row.querySelector('.timeline-row__title')?.textContent).toBe('other-host syslog')
    })

    it('開くとメッセージの全文を等幅・改行を保って出す', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(LOG_TITLE)
      const message = region.querySelector('pre.timeline-row__log-message')!
      expect(message.textContent).toBe('vmhba0: timeout\n  retrying command')
      expect(region).toHaveTextContent('2 件')
    })

    it('1000 文字で切られたメッセージには、切れている旨を出す', async () => {
      setup()
      renderTimeline()
      const long = `${'a'.repeat(999)}…`
      await answer(0, withMetricsAndLogs({ items: [{ ...LOG_ITEM_EXAMPLE, detail: long }], total_items: 1 }))
      const region = await openRow(LOG_TITLE)
      expect(region).toHaveTextContent('1000 文字で切っています')
    })

    it('短いメッセージには、切れている旨を出さない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(LOG_TITLE)
      expect(region).not.toHaveTextContent('1000 文字')
    })

    it('操作は「この対象で絞る」「ここを起点にする」「イベントで開く」「ログで開く」。グラフで開く・ガイドは出さない', async () => {
      setup()
      renderTimeline({ onOpenInMetrics: vi.fn() })
      await answer(0, withMetricsAndLogs())
      const region = await openRow(LOG_TITLE)
      expect(within(region).getByRole('button', { name: 'この対象で絞る' })).toBeInTheDocument()
      expect(within(region).getByRole('button', { name: 'ここを起点にする' })).toBeInTheDocument()
      expect(within(region).getByRole('link', { name: 'イベントで開く' })).toBeInTheDocument()
      expect(within(region).queryByRole('button', { name: 'グラフで開く' })).not.toBeInTheDocument()
      expect(region.querySelector('.timeline-guide')).toBeNull()
    })

    it('「ログで開く」は最初の時刻の 5 分前から最後の時刻の 5 分後までと vCenter を渡す（ホスト・種類は渡せない）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(LOG_TITLE)
      const href = within(region).getByRole('link', { name: 'ログで開く' }).getAttribute('href')!
      expect(href.startsWith('#/logs?')).toBe(true)
      const params = new URLSearchParams(href.split('?')[1])
      expect(params.get('vcenter_id')).toBe(VC)
      expect(params.get('from')).toBe('2026-03-22T00:55:00.000Z')
      expect(params.get('to')).toBe('2026-03-22T01:06:00.000Z')
      expect([...params.keys()].sort()).toEqual(['from', 'to', 'vcenter_id'])
    })

    it('イベント行では今までどおりガイドとログで開くが出る', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const region = await openRow(/VmPoweredOffEvent/)
      expect(within(region).getByRole('link', { name: 'ログで開く' })).toBeInTheDocument()
    })
  })

  describe('省かれた種別の知らせ', () => {
    it('省いていなければ知らせを出さない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await rowButton(LOG_TITLE)
      expect(screen.queryByRole('note')).not.toBeInTheDocument()
    })

    it('ログを省いたときは、一覧から省いたこと・件数はグラフにあること・対処を伝える', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ omitted_sources: [{ source: 'log', reason: 'too_many_rows' }] }))
      const note = await screen.findByRole('note')
      expect(note).toHaveTextContent('ログは件数が多すぎるため、一覧から省いています（件数は上のグラフに出ています）')
      expect(note).toHaveTextContent('期間を短くするか、対象を絞ってください')
    })

    it('メトリクスを省いたときは、グラフにも出ていないと分かる文にする', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ omitted_sources: [{ source: 'metric', reason: 'too_many_rows' }] }))
      const note = await screen.findByRole('note')
      expect(note).toHaveTextContent('メトリクスの超過区間は件数が多すぎるため')
      expect(note).toHaveTextContent('グラフにも出ていません')
      expect(note).toHaveTextContent('しきい値を上げるか、期間を短くするか、対象を絞ってください')
    })

    it('両方省いたときは 1 種別 1 文で並べ、truncated の知らせとも並べて読める', async () => {
      setup()
      renderTimeline()
      await answer(
        0,
        withMetricsAndLogs({
          truncated: true,
          total_items: 1500,
          omitted_sources: [
            { source: 'metric', reason: 'too_many_rows' },
            { source: 'log', reason: 'too_many_rows' },
          ],
        }),
      )
      await rowButton(LOG_TITLE)
      const notes = screen.getAllByRole('note')
      expect(notes).toHaveLength(3)
      expect(notes[0]).toHaveTextContent('1500 件中 3 件を表示しています')
      expect(notes[1]).toHaveTextContent('メトリクスの超過区間')
      expect(notes[2]).toHaveTextContent('ログは件数')
      // 同じ入れ物（リスト）にまとまっていて、続けて読める
      expect(notes[0].parentElement).toBe(notes[2].parentElement)
    })

    it('省いたため一覧が空でも、知らせを出し「出来事はありません」とは言わない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ items: [], total_items: 0, omitted_sources: [{ source: 'log', reason: 'too_many_rows' }] }))
      expect(await screen.findByRole('note')).toHaveTextContent('ログは件数が多すぎる')
      expect(screen.queryByText('この期間に出来事はありません。')).not.toBeInTheDocument()
      // 期間を広げると件数がさらに増えるので、広げるボタンは出さず、短くする・絞る案内だけにする
      expect(screen.queryByRole('button', { name: '期間を広げる' })).not.toBeInTheDocument()
      expect(screen.getByText(/期間を短くするか、対象を絞ってください/, { selector: '.table-empty' })).toBeInTheDocument()
    })

    it('省いていないときの空の一覧には、今までどおり「期間を広げる」が出る', async () => {
      setup()
      renderTimeline()
      await answer(0, emptyViewResponse())
      expect(await screen.findByRole('button', { name: '期間を広げる' })).toBeInTheDocument()
    })

    it('状態の欄は、省いた種別を「（ログは省いています）」と添える（読み上げも同じ）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ omitted_sources: [{ source: 'log', reason: 'too_many_rows' }] }))
      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent('3 件の出来事を表示しています（ログは省いています）。'),
      )
    })

    it('状態の欄: 両方省いたときは省いた順に並べ、truncated とも矛盾しない', async () => {
      setup()
      renderTimeline()
      await answer(
        0,
        withMetricsAndLogs({
          truncated: true,
          total_items: 1500,
          omitted_sources: [
            { source: 'metric', reason: 'too_many_rows' },
            { source: 'log', reason: 'too_many_rows' },
          ],
        }),
      )
      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent(
          '1500 件中 3 件の出来事を表示しています（メトリクス・ログは省いています）。',
        ),
      )
    })

    it('省いていなければ、状態の欄に「省いています」とは書かない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await waitFor(() => expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).toHaveTextContent('3 件の出来事を表示しています。'))
      expect(screen.getByRole('status', { name: 'タイムラインの読み込み' })).not.toHaveTextContent('省いています')
    })
  })

  describe('件数の俯瞰: メトリクス超過とエラーログ', () => {
    const legendTexts = () => [...document.querySelectorAll('.recharts-legend-item-text')].map((e) => e.textContent)

    const rectsOf = (name: string) =>
      [...document.querySelectorAll('.recharts-bar-rectangle path')].filter((r) => r.getAttribute('name')?.includes(name))

    it('エラーログは「件・右の軸」と凡例で伝える。メトリクス超過は凡例ではなく、積み上げの下の帯として説明する', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      expect(legendTexts()).toContain('エラーログ（件・右の軸）')
      expect(legendTexts().join()).not.toContain('メトリクス超過')
      const band = document.querySelector('.timeline-overview__band')!
      expect(band).toBeInTheDocument()
      expect(band).toHaveTextContent('メトリクス超過')
      expect(band).toHaveTextContent('かかっている超過区間の数')
    })

    it('メトリクス超過は積み上げに入れない（棒の高さが「出来事 + 区間数」の和にならない）。帯は濃いほど区間が多い', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      // 積み上げの棒にメトリクスの系列は無く、帯に区間のある時間帯（3 本中 2 本）だけが描かれる
      const bandRects = rectsOf('メトリクス超過')
      const heights = bandRects.map((r) => Number(r.getAttribute('height')))
      expect(heights.filter((h) => h > 0)).toHaveLength(2)
      const stacked = document.querySelector('.timeline-overview__chart .recharts-wrapper')!
      expect(stacked.querySelectorAll('.recharts-bar-rectangle path[name="メトリクス超過"]').length).toBeLessThanOrEqual(3)
      const opacities = bandRects.map((r) => Number(r.getAttribute('fill-opacity') ?? '1')).filter((_, i) => heights[i] > 0)
      // 1 区間の時間帯より 2 区間の時間帯のほうが濃い
      expect(Math.max(...opacities)).toBeGreaterThan(Math.min(...opacities))
    })

    it('ログは積み上げに入れず、右の軸の折れ線にする（桁違いに多くても、ほかの種別の棒が潰れない）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      expect(document.querySelectorAll('.recharts-line').length).toBe(1)
      const axes = [...document.querySelectorAll('.recharts-yAxis')]
      expect(axes.some((a) => a.querySelector('line')?.getAttribute('orientation') === 'right')).toBe(true)
      expect(rectsOf('エラーログ')).toHaveLength(0)
      // 積み上げの棒（イベント）の高さは、ログの 5000 件に引きずられない
      const events = [...document.querySelectorAll('.recharts-bar-rectangle path')].filter(
        (r) => !r.getAttribute('name')?.includes('メトリクス'),
      )
      expect(Math.max(...events.map((r) => Number(r.getAttribute('height'))))).toBeGreaterThan(45)
    })

    it('ログもメトリクスも無ければ、折れ線も帯も出さない', async () => {
      setup()
      renderTimeline()
      await answer(0)
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      expect(document.querySelectorAll('.recharts-line').length).toBe(0)
      expect(document.querySelector('.timeline-overview__band')).toBeNull()
      expect(legendTexts().join()).not.toContain('エラーログ')
    })

    it('メトリクスを省いたときは、overview に値があっても帯を出さない（ログは出す）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ omitted_sources: [{ source: 'metric', reason: 'too_many_rows' }] }))
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      expect(document.querySelector('.timeline-overview__band')).toBeNull()
      expect(legendTexts().join()).toContain('エラーログ')
    })

    it('ログだけを省いたときも、件数は俯瞰に出す（帯も出す）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs({ omitted_sources: [{ source: 'log', reason: 'too_many_rows' }] }))
      await screen.findByRole('application', { name: /件数の俯瞰グラフ/ })
      expect(legendTexts().join()).toContain('エラーログ')
      expect(document.querySelector('.timeline-overview__band')).toBeInTheDocument()
    })

    it('キーボード: 矢印・End・Enter で期間を絞れる（帯があっても今までどおり）', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const chart = await screen.findByRole('application', { name: '件数の俯瞰グラフ' })
      chart.focus()
      fireEvent.keyDown(chart, { key: 'End' })
      fireEvent.keyDown(chart, { key: 'Enter' })
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ from: '2026-03-22T00:40:00.000Z', to: '2026-03-22T01:00:00.000Z' })
    })

    it('キーボードの案内は、メトリクス超過の区間の数を出来事の件数に足さない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const chart = await screen.findByRole('application', { name: '件数の俯瞰グラフ' })
      chart.focus()
      fireEvent.keyDown(chart, { key: 'ArrowRight' })
      // 先頭の棒: イベント 1・メトリクス超過 1 区間
      expect(chart.querySelector('.timeline-overview__announce')).toHaveTextContent('出来事 1 件')
      expect(chart.querySelector('.timeline-overview__announce')).toHaveTextContent('メトリクス超過 1 区間')
    })
  })

  describe('ハイライト: メトリクスとログ', () => {
    it('最初の兆候がメトリクスの行でも、種別とレベルを出し、クリックで一覧の該当行が開く', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      const highlights = await screen.findByLabelText('ハイライト')
      expect(within(highlights).getByText('メトリクス')).toBeInTheDocument()
      fireEvent.click(within(highlights).getByRole('button', { name: /esx01 \/ CPU 使用率が閾値/ }))
      const row = (await rowButton(METRIC_TITLE)).closest('li')!
      expect(row).toHaveClass('timeline-row--revealed')
      expect(row.querySelector('.timeline-row__summary')).toHaveAttribute('aria-expanded', 'true')
    })

    it('最初の兆候がログの行のとき、対象名がタイトルに含まれていれば重ねて出さない', async () => {
      setup()
      renderTimeline()
      const items = [LOG_ITEM_EXAMPLE]
      await answer(
        0,
        withMetricsAndLogs({ items, total_items: 1, highlights: { first_signal: items[0], top_entities: [], new_event_types: [] } }),
      )
      const highlights = await screen.findByLabelText('ハイライト')
      const link = within(highlights).getByRole('button', { name: /vmkernel/ })
      expect(link).toHaveTextContent('esx01.example.com vmkernel')
      expect(link.textContent).not.toContain('esx01.example.com / ')
    })

    it('影響の大きい対象に FQDN や IP が入っても、そのまま出して対象で絞れる', async () => {
      setup()
      renderTimeline()
      await answer(
        0,
        withMetricsAndLogs({
          highlights: {
            first_signal: null,
            top_entities: [
              { entity_name: 'esx01.very-long-subdomain.example.co.jp', vcenter_id: VC, vcenter_name: 'vc-main', item_count: 12, first_seen_utc: '2026-03-22T00:10:00Z' },
              { entity_name: '192.168.100.200', vcenter_id: VC, vcenter_name: 'vc-main', item_count: 3, first_seen_utc: '2026-03-22T00:12:00Z' },
            ],
            new_event_types: [],
          },
        }),
      )
      const highlights = await screen.findByLabelText('ハイライト')
      fireEvent.click(within(highlights).getByRole('button', { name: '192.168.100.200' }))
      await answer(1, emptyViewResponse())
      expect(harness.calls[1].body).toMatchObject({ entity: '192.168.100.200', vcenter_id: VC })
      expect(harness.calls[1].body).not.toHaveProperty('entity_moid')
    })
  })

  describe('インシデントへの紐付け', () => {
    const time = '2026-03-22T00:10:00.123456Z'
    const config = { ...CONFIG_CHANGE, event_count: 22, event_ids: Array.from({ length: 20 }, (_, i) => i + 1) }
    const result = () => {
      const data = populated({}, { timestamp_utc: time })
      return {
        ...data,
        highlights: {
          ...data.highlights,
          config_changes: [config],
          config_changes_total: 1,
          detected_patterns: [DETECTED_PATTERN],
          detected_patterns_total: 1,
        },
      }
    }

    const expectLinkRequest = async (region: HTMLElement, items: unknown[], notice?: string) => {
      const sent = vi.fn()
      harness.extra.set(`/api/incidents/${INCIDENT_ID}/events`, (_url, init) => {
        sent(JSON.parse(String(init?.body)))
        return jsonResponse({
          added: 2,
          results: [{ id: 1, result: 'added', link_id: 1 }, { id: 2, result: 'added', link_id: 2 }, { id: 3, result: 'not_found' }],
        })
      })
      harness.extra.set('/api/incidents?', () => jsonResponse(INCIDENT_LIST))
      fireEvent.click(within(region).getByRole('button', { name: 'インシデントに追加' }))
      const dialog = screen.getByRole('dialog', { name: 'インシデントに追加' })
      const picker = within(dialog)
      if (notice) expect(picker.getByText(notice)).toBeVisible()
      await picker.findByRole('option', { name: INCIDENT_TITLE })
      fireEvent.change(picker.getByRole('combobox', { name: '未解決のインシデント' }), { target: { value: INCIDENT_ID } })
      fireEvent.click(picker.getByRole('button', { name: '追加' }))
      expect(await picker.findByText('2 件を追加しました。1 件は見つかりませんでした')).toBeVisible()
      expect(sent).toHaveBeenCalledWith({ items })
    }

    it.each([
      ['構成変更', config, '22 件のうち、先頭の 20 件を追加します'],
      ['検知した障害パターン', DETECTED_PATTERN, undefined],
    ] as const)('%s はイベント ID と期間を送る', async (name, card, notice) => {
      setup()
      renderTimeline()
      await answer(0, result())
      const region = await screen.findByRole('region', { name })
      await expectLinkRequest(region, card.event_ids.map((id) => ({
        id, occurred_from: card.first_utc, occurred_to: card.last_utc,
      })), notice)
    })

    it('まとめた行は先頭の 1 件とその発生時刻を送る', async () => {
      setup()
      renderTimeline()
      await answer(0, result())
      await openFirstRow()
      const region = screen.getByRole('region', { name: /VmPoweredOffEvent の詳細/ })
      await expectLinkRequest(region, [{ id: 1, occurred_at: time }], 'まとめた 3 件のうち、先頭の 1 件を追加します')
    })

    it('viewer に紐付けの操作を表示しない', async () => {
      setup()
      render(
        <AuthContext.Provider value={{
          me: { ...AUTH_DISABLED_ME, auth_enabled: true, role: 'viewer' },
          hasRole: (role) => role === 'viewer', logout: vi.fn(), refresh: vi.fn(),
        }}>
          <ThemeProvider><TimeZoneProvider><TimelinePanel onError={onError} /></TimeZoneProvider></ThemeProvider>
        </AuthContext.Provider>,
      )
      await answer(0, result())
      await openFirstRow()
      expect(screen.queryByRole('button', { name: 'インシデントに追加' })).toBeNull()
    })
  })
})

