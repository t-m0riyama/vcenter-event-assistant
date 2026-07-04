import type { ReactNode } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PanelErrorBoundary } from './PanelErrorBoundary'

function ThrowOnRender(): ReactNode {
  throw new Error('panel boom')
}

describe('PanelErrorBoundary', () => {
  it('renders children when there is no error', () => {
    render(
      <PanelErrorBoundary panelLabel="チャット">
        <span>panel-ok</span>
      </PanelErrorBoundary>,
    )
    expect(screen.getByText('panel-ok')).toBeInTheDocument()
  })

  it('renders fallback with panel label when child throws', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <PanelErrorBoundary panelLabel="チャット">
        <ThrowOnRender />
      </PanelErrorBoundary>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('チャットを表示できませんでした')
    spy.mockRestore()
  })
})
