import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CollectionFailure } from './CollectionFailure'

const props = {
  state: 'unknown',
  targetName: 'lab',
  lastSuccessAt: null,
  lastFailureAt: null,
  error: null,
  timeZone: 'UTC',
} as const

describe('CollectionFailure', () => {
  it.each([true, false])('時刻表示の設定が %s でも、空のときは呼び出し元の表示を使う', (showFailureTime) => {
    render(<CollectionFailure {...props} showFailureTime={showFailureTime} emptyContent={<span>記録なし</span>} />)

    expect(screen.getByText('記録なし')).toBeInTheDocument()
    expect(screen.queryByText(/最後の失敗/)).not.toBeInTheDocument()
  })

  it('時刻を表示できる場合は、状態が判定不能でも時刻を表示する', () => {
    const lastFailureAt = '2026-11-26T00:00:00Z'
    render(<CollectionFailure {...props} lastFailureAt={lastFailureAt} showFailureTime emptyContent="記録なし" />)

    expect(screen.getByText('最後の失敗').querySelector('time')).toHaveAttribute('datetime', lastFailureAt)
    expect(screen.queryByText('記録なし')).not.toBeInTheDocument()
  })
})
