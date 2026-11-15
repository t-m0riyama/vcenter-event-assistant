import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { ThemeProvider } from '../../theme/ThemeProvider'
import {
  emptyViewResponse,
  installTimelineFetchMock,
  jsonResponse,
  VIEW_RESPONSE_EXAMPLE,
} from '../../test/timelineViewFixtures'
import { TimelinePanel } from './TimelinePanel'

const TEST_TIMEOUT_MS = 15_000
const VC = '11111111-1111-4111-8111-111111111111'

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
function populated(overrides: Record<string, unknown> = {}) {
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
      ref: { event_id: 1, event_type: 'VmPoweredOffEvent' },
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
        { entity_name: 'vm-a', vcenter_id: VC, vcenter_name: 'vc-main', item_count: 3, first_seen_utc: '2026-03-22T00:10:00Z' },
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
  extra: { onOpenSnapshotInMetrics?: (item: never) => void; onOpenInMetrics?: (focus: never) => void; active?: boolean } = {},
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

  it('開くと「生成」を押さずに自動で読み込み、完了と件数をライブ領域で知らせる', async () => {
    setup()
    renderTimeline()
    expect(screen.queryByRole('button', { name: /生成/ })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('読み込み中')
    await answer(0)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('3 件の出来事を表示しています。'))
    expect(screen.getByRole('button', { name: '更新' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '直近 1 時間' })).toHaveAttribute('aria-pressed', 'true')
    expect(window.location.hash).toBe('#/timeline?range=1h')
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

  it('「この対象で絞る」は待たずに対象と vCenter を条件へ入れて読み直し、URL に出る', async () => {
    setup()
    renderTimeline()
    await answer(0)
    await openFirstRow()
    fireEvent.click(screen.getByRole('button', { name: 'この対象で絞る' }))
    await answer(1, populated({ items: [] }))
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC })
    expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('vm-a')
    expect(window.location.hash).toContain('entity=vm-a')
    expect(window.location.hash).toContain(`vcenter_id=${VC}`)
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
    expect(harness.calls[1].body).toMatchObject({ entity: 'vm-a', vcenter_id: VC })
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
    expect(harness.calls[1].body.sources).toEqual(['alert'])
    expect(screen.getByLabelText('アラート')).toBeDisabled() // 最後の 1 つは外せない
    const details = screen.getByText('詳細設定').closest('details')!
    expect(details).not.toHaveAttribute('open')
    const score = within(details).getByLabelText('最小スコア')
    fireEvent.change(score, { target: { value: '40' } })
    fireEvent.blur(score)
    await answer(2, emptyViewResponse())
    expect(harness.calls[2].body.min_score).toBe(40)
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

  it('スナップショットの保存は旧形式のまま（結果は送らない）で、運用メモが必須', async () => {
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
    fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
    const save = await screen.findByRole('button', { name: 'スナップショットを保存' })
    await waitFor(() => expect(save).toBeDisabled())
    fireEvent.change(screen.getByLabelText('運用メモ（必須）'), { target: { value: '保存テスト' } })
    await waitFor(() => expect(save).toBeEnabled())
    fireEvent.click(save)
    await waitFor(() => expect(saved).not.toBeNull())
    expect(saved).toMatchObject({ operator_note: '保存テスト' })
    expect(saved).toHaveProperty('build_request_payload')
    expect(saved).not.toHaveProperty('items')
    expect(saved).not.toHaveProperty('result_payload')
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
})
