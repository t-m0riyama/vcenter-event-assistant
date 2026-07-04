import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TabHelpSection } from './TabHelpSection'

describe('TabHelpSection', () => {
  it('renders summary and user guide path', () => {
    render(
      <TabHelpSection
        entry={{
          summary: '【概要】\nテスト要約',
          userGuideDoc: 'docs/user-guides/summary.md',
          markerId: 'summary',
        }}
      />,
    )
    expect(screen.getByText(/テスト要約/)).toBeInTheDocument()
    expect(screen.getByText('docs/user-guides/summary.md')).toBeInTheDocument()
  })
})
