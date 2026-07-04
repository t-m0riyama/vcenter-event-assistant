import type { ReactNode } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PanelErrorBoundary, PanelShell } from './PanelErrorBoundary'

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

describe('PanelShell', () => {
  it('shows panel-level alert from reportError callback', () => {
    render(
      <PanelShell panelLabel="イベント一覧">
        {(reportError) => (
          <button type="button" onClick={() => reportError('502 failed')}>
            fail
          </button>
        )}
      </PanelShell>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'fail' }))
    expect(screen.getByRole('alert')).toHaveTextContent('502 failed')
  })

  it('clears panel alert when reportError receives null', () => {
    render(
      <PanelShell panelLabel="イベント一覧">
        {(reportError) => (
          <>
            <button type="button" onClick={() => reportError('502 failed')}>
              fail
            </button>
            <button type="button" onClick={() => reportError(null)}>
              clear
            </button>
          </>
        )}
      </PanelShell>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'fail' }))
    expect(screen.getByRole('alert')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'clear' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
