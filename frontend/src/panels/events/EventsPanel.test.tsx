import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EventsPanel } from './EventsPanel'
import { TimeZoneContext } from '../../datetime/timeZoneContext'
import { apiGet } from '../../api'

vi.mock('../../api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn(), apiDelete: vi.fn() }))
vi.mock('../../preferences/useAutoRefreshPreferences', () => ({
  useAutoRefreshPreferences: () => ({ autoRefreshEnabled: false, autoRefreshIntervalMinutes: 1 }),
}))

const VC = '11111111-1111-4111-8111-111111111111'
const VC2 = '22222222-2222-4222-8222-222222222222'

const base = {
  vcenter_id: VC, severity: 'warning', notable_score: 50, message: 'メッセージ',
  user_comment: null, notable_tags: [], user_name: null, entity_type: null,
}

function show() {
  return render(
    <TimeZoneContext.Provider value={{ timeZone: 'UTC', setTimeZone: vi.fn() }}>
      <EventsPanel onError={vi.fn()} />
    </TimeZoneContext.Provider>,
  )
}

function linkParams(link: HTMLElement) {
  return new URLSearchParams(link.getAttribute('href')!.split('?')[1])
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiGet).mockImplementation(async (path: string) => {
    if (path.startsWith('/api/vcenters')) return []
    return {
      total: 2,
      items: [
        { ...base, id: 1, event_type: 'HostConnectionLostEvent', occurred_at: '2026-10-03T01:00:00Z', entity_name: 'esx01' },
        { ...base, id: 2, vcenter_id: VC2, event_type: 'VmPoweredOffEvent', occurred_at: '2026-10-03T02:00:00Z', entity_name: null },
      ],
    }
  })
})

describe('タイムラインで見る', () => {
  it('行の発生時刻・vCenter・対象（entity_name）で開くリンクを置く', async () => {
    show()
    const link = await screen.findByRole('link', { name: /^esx01（.*1:00:00.*）をタイムラインで見る$/ })
    const p = linkParams(link)
    expect(p.get('anchor')).toBe('2026-10-03T01:00:00.000Z')
    expect(p.get('from')).toBe('2026-10-03T00:30:00.000Z')
    expect(p.get('to')).toBe('2026-10-03T01:30:00.000Z')
    expect(p.get('vcenter_id')).toBe(VC)
    expect(p.get('entity')).toBe('esx01')
  })

  it('entity_name が無い行は対象を渡さず、名前に event_type を使う', async () => {
    show()
    const link = await screen.findByRole('link', { name: /^VmPoweredOffEvent（.*2:00:00.*）をタイムラインで見る$/ })
    const p = linkParams(link)
    expect(p.get('anchor')).toBe('2026-10-03T02:00:00.000Z')
    expect(p.get('from')).toBe('2026-10-03T01:30:00.000Z')
    expect(p.get('vcenter_id')).toBe(VC2)
    expect(p.has('entity')).toBe(false)
  })

  it('「前後5分のログ」のリンクの隣（同じ操作の場所）に置く', async () => {
    show()
    const row = (await screen.findByText('HostConnectionLostEvent')).closest('tr')!
    expect(within(row).getByRole('link', { name: /をタイムラインで見る$/ })).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: '前後5分のログ' })).toBeInTheDocument()
  })
})
