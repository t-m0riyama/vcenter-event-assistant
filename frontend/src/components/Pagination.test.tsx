import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Pagination } from './Pagination'

const props = { total: 120, start: 51, end: 100, canPrev: true, canNext: true, onPrev: vi.fn(), onNext: vi.fn() }

describe('Pagination', () => {
  it('labels the top and bottom controls and announces the count only at the top', () => {
    render(<><Pagination position="top" {...props} /><Pagination position="bottom" {...props} /></>)
    expect(screen.getByRole('navigation', { name: 'ページ切り替え（上）' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'ページ切り替え（下）' })).toBeInTheDocument()
    expect(screen.getAllByText('全 120 件中 51–100 件を表示')).toHaveLength(2)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('disables the buttons at the ends and while loading', () => {
    const { rerender } = render(<Pagination position="top" {...props} canPrev={false} />)
    expect(screen.getByRole('button', { name: '前へ' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '次へ' })).toBeEnabled()
    rerender(<Pagination position="top" {...props} loading />)
    expect(screen.getByRole('button', { name: '次へ' })).toBeDisabled()
    expect(screen.getByText('読み込み中…')).toBeInTheDocument()
  })

  it('shows zero results', () => {
    render(<Pagination position="top" {...props} total={0} start={0} end={0} canPrev={false} canNext={false} />)
    expect(screen.getByText('全 0 件')).toBeInTheDocument()
  })

  it('scrolls back to the top of the panel when the bottom controls are used', () => {
    const onNext = vi.fn()
    render(<div className="panel"><Pagination position="bottom" {...props} onNext={onNext} /></div>)
    const panel = document.querySelector('.panel') as HTMLElement
    panel.scrollIntoView = vi.fn()
    fireEvent.click(screen.getByRole('button', { name: '次へ' }))
    expect(onNext).toHaveBeenCalled()
    expect(panel.scrollIntoView).toHaveBeenCalledWith({ block: 'start' })
  })
})
