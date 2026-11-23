import { StrictMode } from 'react'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { jsonResponse } from '../../test/timelineViewFixtures'
import { TimelineImpactSection } from './TimelineImpactSection'
import { defaultImpactTime } from './timelineModel'

const from = '2026-03-22T00:00:00Z'
const at = '2026-03-22T00:10:00Z'
const to = '2026-03-22T01:00:00Z'
const timeZone = 'Asia/Tokyo'
const vcenterId = '11111111-1111-4111-8111-111111111111'
const vm = { moid: 'vm-12', entity_type: 'VirtualMachine', name: 'app' }
const host = { moid: 'host-2', entity_type: 'HostSystem', name: 'esx-02' }
const impact = {
  target: vm,
  at,
  status: 'ok',
  recorded_since: from,
  last_success_at: to,
  observed_before: from,
  observed_after: to,
  groups: [],
  changes: { items: [], total: 0 },
}

function show(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ...impact, ...overrides })))
  const onFilterEntity = vi.fn()
  render(<TimelineImpactSection
    vcenterId={vcenterId} entityMoid="vm-12" period={{ from, to, defaultAt: at, anchor: null }}
    timeZone={timeZone} onFilterEntity={onFilterEntity}
  />)
  return onFilterEntity
}

afterEach(() => vi.unstubAllGlobals())

describe('defaultImpactTime', () => {
  it('起点、最初の兆候、期間の始まりの順に使う', () => {
    expect(defaultImpactTime(from, to, at)).toBe(to)
    expect(defaultImpactTime(from, null, at)).toBe(at)
    expect(defaultImpactTime(from, null, null)).toBe(from)
    expect(defaultImpactTime(from, null, '2026-03-22T00:10:00.123456')).toBe('2026-03-22T00:10:00.123456Z')
    expect(defaultImpactTime(from, '2026-03-22T09:10:00+09:00', null)).toBe('2026-03-22T09:10:00+09:00')
  })
})

describe('TimelineImpactSection', () => {
  it.each([
    ['not_recorded', `この時点の関係は記録されていません（記録は ${formatIsoInTimeZone(from, timeZone)} から）。`],
    ['unknown_target', 'この対象の関係の記録がありません。'],
    ['unsupported_type', 'この種類の対象の影響範囲は出せません。'],
    ['absent_at_time', `この時点の観測では、この対象は見えていませんでした（直前: ${formatIsoInTimeZone(from, timeZone)}、直後: ${formatIsoInTimeZone(to, timeZone)}）。`],
    ['stale', `この時点の前後は ${formatIsoInTimeZone(from, timeZone)} と ${formatIsoInTimeZone(to, timeZone)} に観測しています。その間の変化は反映していません。`],
  ])('%s の説明を出す', async (status, message) => {
    show({ status })
    expect(await screen.findByText(message)).toBeInTheDocument()
  })

  it('未収集のとき設定の vCenter 一覧に案内する', async () => {
    show({ status: 'not_recorded', recorded_since: null })
    expect(await screen.findByText(/まだ関係を収集していません/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '設定の vCenter 一覧' })).toHaveAttribute('href', '#/settings/vcenters')
  })

  it('記録や前後の観測がないときも案内する', async () => {
    show({ status: 'stale', observed_before: null, observed_after: null, last_success_at: null })
    expect(await screen.findByText(/その間の変化は反映していません/)).toHaveTextContent('直前の観測なし・直後の観測なし')
    expect(screen.getByText(/最後の収集/)).toHaveTextContent('未収集')
  })

  it('種類別の件数、折りたたみ、表示上限、現在見えない項目を出し、moid で絞る', async () => {
    const onFilterEntity = show({
      groups: [
        { relation: 'hosts', items: [{ ...host, removed: true }], total: 1 },
        {
          relation: 'vms',
          items: Array.from({ length: 8 }, (_, i) => ({ ...vm, moid: `vm-${i}`, name: `app-${i}`, removed: false })),
          total: 10,
        },
      ],
    })
    expect(await screen.findByText('ホスト（1 件）')).toBeInTheDocument()
    expect(screen.getByText('（現在は見えない）')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'esx-02 で絞る' }))
    expect(onFilterEntity).toHaveBeenCalledWith('esx-02', vcenterId, 'host-2')
    const summary = screen.getByRole('heading', { level: 4, name: 'VM（10 件）' })
    expect(summary.closest('details')).not.toHaveAttribute('open')
    expect(within(summary.closest('details')!).getByText('ほか 2 件')).toBeInTheDocument()
    expect(screen.getByText(/最後の収集/)).toHaveTextContent(formatIsoInTimeZone(to, timeZone))
  })

  it('同時刻・同じ種類の開始と終了を一行にまとめ、残りを個別に表示する', async () => {
    show({
      changes: { items: [
        { kind: 'vm_host', other: { ...host, moid: 'host-3', name: 'esx-03' }, at, action: 'opened' },
        { kind: 'vm_host', other: host, at, action: 'closed' },
        { kind: 'vm_host', other: { ...host, moid: 'host-4', name: 'esx-04' }, at: to, action: 'opened' },
        { kind: 'host_cluster', other: { moid: 'domain-c1', entity_type: 'ClusterComputeResource', name: 'cluster-a' }, at, action: 'closed' },
      ], total: 5 },
    })
    const summary = await screen.findByText('期間中の変化（関係の開始・終了 5 件）')
    const details = summary.closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(within(details).getByText(/ホスト: esx-02 → esx-03/)).toHaveTextContent(formatIsoInTimeZone(at, timeZone))
    expect(within(details).queryByText(/esx-02.*終了|esx-03.*開始/)).not.toBeInTheDocument()
    expect(within(details).getByText(/esx-04.*開始/)).toHaveTextContent(formatIsoInTimeZone(to, timeZone))
    expect(within(details).getByText(/cluster-a.*終了/)).toHaveTextContent(formatIsoInTimeZone(at, timeZone))
    expect(within(details).getByText('ほか 1 件')).toBeInTheDocument()
  })

  it('置き換わった要求を中止し、応答が遅れて届いても新しい結果を保持する', async () => {
    const requests: { signal?: AbortSignal | null; resolve: (response: Response) => void }[] = []
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) =>
      new Promise<Response>((resolve) => requests.push({ signal: init?.signal, resolve })),
    ))
    render(
      <StrictMode>
        <TimelineImpactSection
          vcenterId={vcenterId} entityMoid="vm-12" period={{ from, to, defaultAt: at, anchor: null }}
          timeZone={timeZone} onFilterEntity={vi.fn()}
        />
      </StrictMode>,
    )
    const live = screen.getByRole('region', { name: '影響範囲' }).querySelector('[aria-live="polite"]')
    await waitFor(() => expect(requests).toHaveLength(1))
    fireEvent.change(screen.getByLabelText('影響範囲の時点'), { target: { value: 'end' } })
    await waitFor(() => expect(requests).toHaveLength(2))
    expect(requests[0].signal?.aborted).toBe(true)
    expect(requests[1].signal?.aborted).toBe(false)
    await act(async () => {
      requests[1].resolve(jsonResponse({ ...impact, target: { ...vm, name: '新しい結果' } }))
    })
    expect(await screen.findByText(/新しい結果 の関係/)).toBeInTheDocument()
    await act(async () => {
      requests[0].resolve(jsonResponse({ ...impact, target: { ...vm, name: '古い結果' } }))
    })
    expect(screen.queryByText(/古い結果/)).not.toBeInTheDocument()
    expect(screen.getByText(/新しい結果 の関係/)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '影響範囲' }).querySelector('[aria-live="polite"]')).toBe(live)
  })
})
