import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { IncidentTimeline } from '../../api/schemas'
import { IncidentTimelinePanel } from './IncidentTimelinePanel'

describe('IncidentTimelinePanel', () => {
  it('同一時刻では Alert → Event → Metric の順で表示する', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'metric', title: 'M' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' },
          ],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    const column = screen.getByRole('listitem', { name: '2026-05-07T00:00:00Z のタイムライン' })
    const chips = within(column).getAllByTestId('incident-timeline-item')
    expect(chips.map((el) => el.textContent)).toEqual(['A', 'E', 'M'])
  })

  it('種別に応じて色分けクラスが付与される', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'metric', title: 'M' },
          ],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getByText('A')).toHaveClass('incident-timeline__item--alert')
    expect(screen.getByText('E')).toHaveClass('incident-timeline__item--event')
    expect(screen.getByText('M')).toHaveClass('incident-timeline__item--metric')
  })

  it('同時刻10件超過時は +N件 で展開できる', () => {
    const items = Array.from({ length: 12 }, (_, i) => ({
      timestamp_utc: '2026-05-07T00:00:00Z',
      kind: (i === 0 ? 'alert' : 'event') as 'alert' | 'event' | 'metric',
      title: `item-${i + 1}`,
    }))
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items,
          visible_items: items.slice(0, 10),
          hidden_count: 2,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getAllByTestId('incident-timeline-item')).toHaveLength(10)
    fireEvent.click(screen.getByRole('button', { name: '+2件' }))
    expect(screen.getAllByTestId('incident-timeline-item')).toHaveLength(12)
  })

  it('items が空でも hidden_count があれば +N件 を表示する', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [],
          visible_items: [],
          hidden_count: 3,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getByRole('button', { name: '+3件' })).toBeInTheDocument()
  })

  it('ソース(kind)フィルタで表示項目を絞り込める', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'metric', title: 'M' },
          ],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    fireEvent.change(screen.getByLabelText('ソース'), { target: { value: 'event' } })
    const chips = screen.getAllByTestId('incident-timeline-item')
    expect(chips.map((el) => el.textContent)).toEqual(['E'])
  })

  it('重要度フィルタで表示項目を絞り込める（alert=high, event=medium, metric=low）', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E' },
            { timestamp_utc: '2026-05-07T00:00:00Z', kind: 'metric', title: 'M' },
          ],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    fireEvent.change(screen.getByLabelText('重要度'), { target: { value: 'high' } })
    const chips = screen.getAllByTestId('incident-timeline-item')
    expect(chips.map((el) => el.textContent)).toEqual(['A'])
  })
})
