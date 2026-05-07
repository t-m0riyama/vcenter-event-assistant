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

  it('サマリーモードでフィルタ適用時は +N件 を過大表示しない', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [],
          visible_items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'event', title: 'E' }],
          hidden_count: 99,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    fireEvent.change(screen.getByLabelText('ソース'), { target: { value: 'event' } })
    expect(screen.queryByRole('button', { name: '+99件' })).not.toBeInTheDocument()
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

  it('タイムラインは横軸表示のためスクロールコンテナ内に配置される', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' }],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    const timelineList = screen.getByRole('list', { name: 'インシデント統合タイムライン' })
    expect(timelineList).toHaveClass('incident-timeline--horizontal')
    expect(timelineList.parentElement).toHaveClass('incident-timeline__scroll')
  })

  it('短期間バケットは HH:mm-HH:mm で表示する', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          bucket_start_utc: '2026-05-07T00:00:00Z',
          bucket_end_utc: '2026-05-07T06:00:00Z',
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'A' }],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getByText('00:00-06:00')).toBeInTheDocument()
  })

  it('表示対象が複数日に跨ると短期間バケットでも開始時刻に日付を付ける', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-08T17:38:00Z',
          bucket_start_utc: '2026-05-08T17:38:00Z',
          bucket_end_utc: '2026-05-08T18:38:00Z',
          items: [{ timestamp_utc: '2026-05-08T17:38:00Z', kind: 'alert', title: 'A' }],
          visible_items: [],
          hidden_count: 0,
        },
        {
          timestamp_utc: '2026-05-07T16:42:00Z',
          bucket_start_utc: '2026-05-07T16:42:00Z',
          bucket_end_utc: '2026-05-07T17:42:00Z',
          items: [{ timestamp_utc: '2026-05-07T16:42:00Z', kind: 'event', title: 'E' }],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getByText('05/08 17:38-18:38')).toBeInTheDocument()
    expect(screen.getByText('05/07 16:42-17:42')).toBeInTheDocument()
  })

  it('長期間バケットは MM/DD HH:mm-HH:mm で表示する', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-01T00:00:00Z',
          bucket_start_utc: '2026-05-01T00:00:00Z',
          bucket_end_utc: '2026-05-03T12:00:00Z',
          items: [{ timestamp_utc: '2026-05-01T00:00:00Z', kind: 'alert', title: 'A' }],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }
    render(<IncidentTimelinePanel timeline={timeline} />)

    expect(screen.getByText('05/01 00:00-12:00')).toBeInTheDocument()
  })

  it('sortOrder で時刻列の左右順を切り替える（asc=古→新, desc=新→古）', () => {
    const timeline: IncidentTimeline = {
      columns: [
        {
          timestamp_utc: '2026-05-07T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-07T00:00:00Z', kind: 'alert', title: 'middle' }],
          visible_items: [],
          hidden_count: 0,
        },
        {
          timestamp_utc: '2026-05-06T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-06T00:00:00Z', kind: 'event', title: 'oldest' }],
          visible_items: [],
          hidden_count: 0,
        },
        {
          timestamp_utc: '2026-05-08T00:00:00Z',
          items: [{ timestamp_utc: '2026-05-08T00:00:00Z', kind: 'metric', title: 'newest' }],
          visible_items: [],
          hidden_count: 0,
        },
      ],
    }

    const { rerender } = render(<IncidentTimelinePanel timeline={timeline} sortOrder="asc" />)
    expect(
      screen.getAllByRole('listitem').map((item) => item.getAttribute('aria-label')),
    ).toEqual([
      '2026-05-06T00:00:00Z のタイムライン',
      '2026-05-07T00:00:00Z のタイムライン',
      '2026-05-08T00:00:00Z のタイムライン',
    ])

    rerender(<IncidentTimelinePanel timeline={timeline} sortOrder="desc" />)
    expect(
      screen.getAllByRole('listitem').map((item) => item.getAttribute('aria-label')),
    ).toEqual([
      '2026-05-08T00:00:00Z のタイムライン',
      '2026-05-07T00:00:00Z のタイムライン',
      '2026-05-06T00:00:00Z のタイムライン',
    ])
  })
})
