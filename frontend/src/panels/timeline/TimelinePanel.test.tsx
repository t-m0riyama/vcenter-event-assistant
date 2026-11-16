import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TimeZoneProvider } from '../../datetime/TimeZoneProvider'
import { DISPLAY_TIME_ZONE_STORAGE_KEY } from '../../datetime/timeZoneStorage'
import { ThemeProvider } from '../../theme/ThemeProvider'
import {
  emptyViewResponse,
  installTimelineFetchMock,
  jsonResponse,
  LOG_ITEM_EXAMPLE,
  METRIC_ITEM_EXAMPLE,
  METRIC_ITEM_LEGACY_EXAMPLE,
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
    const openSnapshot = async (item: unknown, detail: unknown) => {
      setup({ snapshots: [item] })
      harness.extra.set(`/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`, () => jsonResponse(detail))
      renderTimeline()
      await answer(0, emptyViewResponse())
      fireEvent.click(screen.getByRole('button', { name: /スナップショット/ }))
      fireEvent.click(await screen.findByRole('button', { name: '結果つきメモ' }))
    }

    it('開くと保存済みの結果を表示し、「保存時点の内容」と保存日時を注記し、現在のデータは取りに行かない', async () => {
      await openSnapshot(listItem(), detailOf())
      const note = await screen.findByRole('note', { name: '保存時点の内容' })
      expect(note).toHaveTextContent('保存時点の内容')
      expect(note).toHaveTextContent(/保存した日時: .*3\/10\/26.*3:30/)
      expect(await screen.findByRole('status')).toHaveTextContent('3 件の出来事を表示しています。')
      expect(await rowButton(/VmPoweredOffEvent/)).toBeInTheDocument()
      // 条件には保存時の値が入る（URL にも反映）
      expect(screen.getByLabelText('対象（ホスト・VM 名）')).toHaveValue('esx01')
      expect(window.location.hash).toContain('from=2026-03-10T00%3A00%3A00.000Z')
      // 再集計の要求は出ていない（最初の読み込みの 1 本だけ）
      expect(harness.calls).toHaveLength(1)
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
      expect(screen.queryByRole('note', { name: '保存時点の内容' })).not.toBeInTheDocument()
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

    it('保存済みの結果がフロントのスキーマで読めないときは、黙らず「いまの形式で読めない」と注記して再集計する', async () => {
      const bad = detailOf({ result: { ...populated(), items: [{ ...populated().items[0], kind: 'k8s' }] } })
      await openSnapshot(listItem(), bad)
      await answer(1, emptyViewResponse())
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
        expect(screen.getByRole('status')).toHaveTextContent('3 件の出来事を表示しています（ログは省いています）。'),
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
        expect(screen.getByRole('status')).toHaveTextContent(
          '1500 件中 3 件の出来事を表示しています（メトリクス・ログは省いています）。',
        ),
      )
    })

    it('省いていなければ、状態の欄に「省いています」とは書かない', async () => {
      setup()
      renderTimeline()
      await answer(0, withMetricsAndLogs())
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('3 件の出来事を表示しています。'))
      expect(screen.getByRole('status')).not.toHaveTextContent('省いています')
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
    })
  })
})

