import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { TimeZoneProvider } from './TimeZoneProvider'
import { ZonedRangeFields } from './ZonedRangeFields'
import type { ZonedRangeParts } from './zonedRangeParts'
import { EMPTY_ZONED_RANGE_PARTS } from './zonedRangeParts'

const empty: ZonedRangeParts = EMPTY_ZONED_RANGE_PARTS

describe('ZonedRangeFields', () => {
  it('onQuickPreset があるときクイックは onQuickPreset のみ呼び onChange は呼ばない', () => {
    const onChange = vi.fn()
    const onQuickPreset = vi.fn()
    render(
      <TimeZoneProvider>
        <ZonedRangeFields value={empty} onChange={onChange} onQuickPreset={onQuickPreset} />
      </TimeZoneProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '過去 24 時間' }))
    expect(onQuickPreset).toHaveBeenCalledTimes(1)
    expect(onQuickPreset).toHaveBeenCalledWith(86400000)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('onQuickPreset がないときクイックは onChange にプリセットを渡す', () => {
    const onChange = vi.fn()
    render(
      <TimeZoneProvider>
        <ZonedRangeFields value={empty} onChange={onChange} />
      </TimeZoneProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: '過去 24 時間' }))
    expect(onChange).toHaveBeenCalled()
    const arg = onChange.mock.calls[0][0] as ZonedRangeParts
    expect(arg.fromDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(arg.toDate).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
