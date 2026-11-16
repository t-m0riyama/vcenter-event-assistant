import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { parseTimelineHash } from '../routing/timelineHash'
import { TimelineLink } from './TimelineLink'

const VC = '11111111-1111-4111-8111-111111111111'

describe('TimelineLink', () => {
  it('「タイムラインで見る」の通常のリンクで、href に起点・vCenter・対象を持つ', () => {
    render(<TimelineLink at="2026-03-22T01:00:00Z" vcenterId={VC} entity="esx01" ariaLabel="esx01 の 01:00 をタイムラインで見る" />)
    const link = screen.getByRole('link', { name: 'esx01 の 01:00 をタイムラインで見る' })
    expect(link).toHaveTextContent('タイムラインで見る')
    const href = link.getAttribute('href')!
    expect(href.startsWith('#/timeline?')).toBe(true)
    const { conditions } = parseTimelineHash(href)!
    expect(conditions.anchor).toBe('2026-03-22T01:00:00.000Z')
    expect(conditions.vcenterId).toBe(VC)
    expect(conditions.entity).toBe('esx01')
  })

  it('aria-label が無ければ文言がそのまま名前になる', () => {
    render(<TimelineLink at="2026-03-22T01:00:00Z" />)
    expect(screen.getByRole('link', { name: 'タイムラインで見る' })).toBeInTheDocument()
  })

  it('時刻が読めないときは何も描画しない', () => {
    const { container } = render(<TimelineLink at="broken" />)
    expect(container).toBeEmptyDOMElement()
    const { container: c2 } = render(<TimelineLink at={null} />)
    expect(c2).toBeEmptyDOMElement()
  })
})
