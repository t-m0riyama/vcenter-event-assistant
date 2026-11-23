import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SummaryPanel } from './SummaryPanel'
import { TimeZoneContext } from '../../datetime/timeZoneContext'
import { apiGet } from '../../api'

vi.mock('../../api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() }))
vi.mock('../../preferences/useAutoRefreshPreferences', () => ({
  useAutoRefreshPreferences: () => ({ autoRefreshEnabled: false, autoRefreshIntervalMinutes: 1 }),
}))
vi.mock('../../preferences/useSummaryTopNotableMinScore', () => ({
  useSummaryTopNotableMinScore: () => ({ topNotableMinScore: 40, setTopNotableMinScore: vi.fn() }),
}))

const VC = '11111111-1111-4111-8111-111111111111'
const VC2 = '22222222-2222-4222-8222-222222222222'
const VC3 = '33333333-3333-4333-8333-333333333333'
const VC4 = '44444444-4444-4444-8444-444444444444'

const summary = {
  vcenter_count: 1,
  events_last_24h: 2,
  notable_events_last_24h: 1,
  top_notable_events: [
    {
      id: 1, vcenter_id: VC, occurred_at: '2026-10-03T01:00:00Z', event_type: 'HostConnectionLostEvent',
      message: 'ホストが切断', severity: 'warning', notable_score: 50, entity_name: 'esx01', entity_moid: 'host-10', user_comment: null,
    },
    {
      id: 2, vcenter_id: VC2, occurred_at: '2026-10-03T02:00:00Z', event_type: 'VmPoweredOffEvent',
      message: 'VM 停止', severity: 'info', notable_score: 45, entity_name: null, entity_moid: 'vm-20', user_comment: null,
    },
  ],
  top_event_types_24h: [],
  high_cpu_hosts: [
    { vcenter_id: VC3, vcenter_label: 'vc-3', entity_name: 'esxi-cpu', entity_moid: 'host-1', value: 91.2, sampled_at: '2026-10-03T03:00:00Z' },
  ],
  high_mem_hosts: [
    { vcenter_id: VC4, vcenter_label: 'vc-4', entity_name: 'esxi-mem', entity_moid: 'host-2', value: 88.4, sampled_at: '2026-10-03T03:05:00Z' },
  ],
}

function show() {
  return render(
    <TimeZoneContext.Provider value={{ timeZone: 'UTC', setTimeZone: vi.fn() }}>
      <SummaryPanel onError={vi.fn()} />
    </TimeZoneContext.Provider>,
  )
}

function linkParams(link: HTMLElement) {
  return new URLSearchParams(link.getAttribute('href')!.split('?')[1])
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiGet).mockResolvedValue(summary)
})

describe('タイムラインで見る', () => {
  it('要注意イベントの行に、発生時刻・vCenter・対象で開くリンクを置く', async () => {
    show()
    const link = await screen.findByRole('link', { name: /^esx01（.*1:00:00.*）をタイムラインで見る$/ })
    const p = linkParams(link)
    expect(p.get('anchor')).toBe('2026-10-03T01:00:00.000Z')
    expect(p.get('from')).toBe('2026-10-03T00:30:00.000Z')
    expect(p.get('to')).toBe('2026-10-03T01:30:00.000Z')
    expect(p.get('vcenter_id')).toBe(VC)
    expect(p.get('entity')).toBe('esx01')
    expect(p.get('entity_moid')).toBe('host-10')
  })

  it('名前が無い要注意イベントは vCenter と moid を渡し、リンクの名前には event_type を使う', async () => {
    show()
    const link = await screen.findByRole('link', { name: /^VmPoweredOffEvent（.*2:00:00.*）をタイムラインで見る$/ })
    const p = linkParams(link)
    expect(p.get('anchor')).toBe('2026-10-03T02:00:00.000Z')
    expect(p.get('vcenter_id')).toBe(VC2)
    expect(p.get('entity_moid')).toBe('vm-20')
    expect(p.has('entity')).toBe(false)
  })

  it('高 CPU と高メモリの行は、それぞれの行の時刻・vCenter・ホスト名を持ち、aria-label で表を区別できる', async () => {
    show()
    const cpu = await screen.findByRole('link', { name: /^esxi-cpu・CPU（.*3:00:00.*）をタイムラインで見る$/ })
    const cp = linkParams(cpu)
    expect(cp.get('anchor')).toBe('2026-10-03T03:00:00.000Z')
    expect(cp.get('from')).toBe('2026-10-03T02:30:00.000Z')
    expect(cp.get('to')).toBe('2026-10-03T03:30:00.000Z')
    expect(cp.get('vcenter_id')).toBe(VC3)
    expect(cp.get('entity')).toBe('esxi-cpu')
    expect(cp.get('entity_moid')).toBe('host-1')

    const mem = screen.getAllByRole('link', { name: /^esxi-mem・メモリ（.*3:05:00.*）をタイムラインで見る$/ })
    expect(mem).toHaveLength(1)
    const mp = linkParams(mem[0])
    expect(mp.get('anchor')).toBe('2026-10-03T03:05:00.000Z')
    expect(mp.get('from')).toBe('2026-10-03T02:35:00.000Z')
    expect(mp.get('to')).toBe('2026-10-03T03:35:00.000Z')
    expect(mp.get('vcenter_id')).toBe(VC4)
    expect(mp.get('entity')).toBe('esxi-mem')
    expect(mp.get('entity_moid')).toBe('host-2')
  })

  it('3 つの表は横スクロールの入れ物に入っている', async () => {
    show()
    await screen.findByText('ホストが切断')
    const tables = document.querySelectorAll('table')
    const withLinks = [...tables].filter((t) => t.querySelector('a.timeline-link'))
    expect(withLinks).toHaveLength(3)
    for (const t of withLinks) expect(t.parentElement).toHaveClass('table-scroll')
  })

  it('リンクは行の末尾の操作の列に入る', async () => {
    show()
    const row = (await screen.findByText('ホストが切断')).closest('tr')!
    expect(within(row).getByRole('link', { name: /をタイムラインで見る$/ })).toBeInTheDocument()
  })
})
