import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SettingsListRow } from './SettingsListRow'

describe('SettingsListRow', () => {
  it('見出しを押すと開閉し、読み上げ名は状態に関係なく渡した名前のまま', () => {
    render(
      <ul className="settings-list">
        <SettingsListRow title="ルール A" preview="スコア 80 以上" ariaLabel="ルール A、警告">
          <p>中身</p>
        </SettingsListRow>
      </ul>,
    )
    const summary = screen.getByLabelText('ルール A、警告')
    const details = summary.closest('details')
    expect(details).not.toHaveAttribute('open')
    expect(summary).toHaveTextContent('スコア 80 以上')
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
    expect(summary).toHaveAttribute('aria-label', 'ルール A、警告')
  })

  it('defaultOpen なら最初から開く', () => {
    render(
      <ul>
        <SettingsListRow title="新しいサンプル" ariaLabel="新しいサンプル" defaultOpen>
          <p>中身</p>
        </SettingsListRow>
      </ul>,
    )
    expect(screen.getByLabelText('新しいサンプル').closest('details')).toHaveAttribute('open')
  })
})
