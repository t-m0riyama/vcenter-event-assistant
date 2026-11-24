import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SeverityBadge } from './badges'

describe('SeverityBadge', () => {
  it.each([
    ['critical', 'critical'], ['  CRIT  ', 'critical'], ['panic', 'critical'], ['fatal', 'critical'],
    ['alert', 'critical'], ['emerg', 'critical'], ['error', 'error'], ['Err', 'error'],
    ['warning', 'warning'], [' WARN ', 'warning'], ['info', 'info'],
  ])('maps %j to the %s style and keeps the log word', (severity, style) => {
    render(<SeverityBadge severity={severity} />)
    expect(screen.getByText(severity.trim())).toHaveClass('badge', `badge--${style}`)
  })

  it('uses the neutral badge for unknown values and a dash for whitespace', () => {
    render(<><SeverityBadge severity="custom" /><SeverityBadge severity=" " /></>)
    expect(screen.getByText('custom').className).toBe('badge')
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
