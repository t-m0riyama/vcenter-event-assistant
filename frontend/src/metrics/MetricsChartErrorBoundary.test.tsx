import type { ReactNode } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MetricsChartErrorBoundary } from './MetricsChartErrorBoundary'

function ThrowOnRender(): ReactNode {
  throw new Error('chart boom')
}

function OkChild() {
  return <span>chart-ok</span>
}

describe('MetricsChartErrorBoundary', () => {
  it('renders children when there is no error', () => {
    render(
      <MetricsChartErrorBoundary>
        <OkChild />
      </MetricsChartErrorBoundary>,
    )
    expect(screen.getByText('chart-ok')).toBeInTheDocument()
  })

  it('renders fallback with role=status when child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <MetricsChartErrorBoundary>
        <ThrowOnRender />
      </MetricsChartErrorBoundary>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('チャートを表示できませんでした')
    spy.mockRestore()
  })
})
