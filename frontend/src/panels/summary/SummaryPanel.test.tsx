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

const summary = {
  vcenter_count: 1,
  events_last_24h: 2,
  notable_events_last_24h: 1,
  top_notable_events: [
    {
      id: 1, vcenter_id: VC, occurred_at: '2026-10-03T01:00:00Z', event_type: 'HostConnectionLostEvent',
      message: 'ホストが切断', severity: 'warning', notable_score: 50, entity_name: 'esx01', user_comment: null,
    },
    {
      id: 2, vcenter_id: VC, occurred_at: '2026-10-03T02:00:00Z', event_type: 'VmPoweredOffEvent',
      message: 'VM 停止', severity: 'info', notable_score: 45, entity_name: null, user_comment: null,
    },
  ],
  top_event_types_24h: [],
  high_cpu_hosts: [
    { vcenter_id: VC, vcenter_label: 'vc-1', entity_name: 'esxi-1', entity_moid: 'host-1', value: 91.2, sampled_at: '2026-10-03T03:00:00Z' },
  ],
  high_mem_hosts: [
    { vcenter_id: VC, vcenter_label: 'vc-1', entity_name: 'esxi-1', entity_moid: 'host-1', value: 88.4, sampled_at: '2026-10-03T03:05:00Z' },
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
  })

  it('要注意イベントで entity_name が無い行は対象を渡さず、名前に event_type を使う', async () => {
    show()
    const link = await screen.findByRole('link', { name: /^VmPoweredOffEvent（.*2:00:00.*）をタイムラインで見る$/ })
    const p = linkParams(link)
    expect(p.get('anchor')).toBe('2026-10-03T02:00:00.000Z')
    expect(p.get('vcenter_id')).toBe(VC)
    expect(p.has('entity')).toBe(false)
  })

  it('高 CPU と高メモリの両方の行に、サンプル時刻・vCenter・ホスト名で開くリンクを置く', async () => {
    show()
    const cpu = await screen.findByRole('link', { name: /^esxi-1（.*3:00:00.*）をタイムラインで見る$/ })
    const cpuParams = linkParams(cpu)
    expect(cpuParams.get('anchor')).toBe('2026-10-03T03:00:00.000Z')
    expect(cpuParams.get('from')).toBe('2026-10-03T02:30:00.000Z')
    expect(cpuParams.get('to')).toBe('2026-10-03T03:30:00.000Z')
    expect(cpuParams.get('vcenter_id')).toBe(VC)
    expect(cpuParams.get('entity')).toBe('esxi-1')

    const mem = screen.getAllByRole('link', { name: /^esxi-1（.*3:05:00.*）をタイムラインで見る$/ })
    expect(mem).toHaveLength(1)
    expect(linkParams(mem[0]).get('anchor')).toBe('2026-10-03T03:05:00.000Z')
  })

  it('リンクは行の末尾の操作の列に入る', async () => {
    show()
    const row = (await screen.findByText('ホストが切断')).closest('tr')!
    expect(within(row).getByRole('link', { name: /をタイムラインで見る$/ })).toBeInTheDocument()
  })
})
