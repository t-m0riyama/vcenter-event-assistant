import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { calendarDay, formatTick, spansCalendarDays, usePointerRangeSelection } from './timelineChartHelpers'

describe('usePointerRangeSelection', () => {
  it('同じ棒で離せばクリック（その 1 本）として選ぶ', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => usePointerRangeSelection(onSelect))
    act(() => result.current.down(3))
    act(() => result.current.up())
    expect(onSelect).toHaveBeenCalledWith(3, 3)
    expect(result.current.range).toBeNull()
  })

  it('別の棒まで動かして離せばドラッグとして選ぶ（逆向きでも範囲は昇順）。押している間は選択中の範囲を返す', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => usePointerRangeSelection(onSelect))
    act(() => result.current.down(5))
    act(() => result.current.move(2))
    expect(result.current.range).toEqual([2, 5])
    act(() => result.current.up())
    expect(onSelect).toHaveBeenCalledWith(5, 2)
  })

  it('押していないときの動きと離す操作は何もせず、グラフの外に出たら選択を取りやめる', () => {
    const onSelect = vi.fn()
    const { result } = renderHook(() => usePointerRangeSelection(onSelect))
    act(() => result.current.move(1))
    act(() => result.current.up())
    expect(onSelect).not.toHaveBeenCalled()
    act(() => result.current.down(1))
    act(() => result.current.cancel())
    act(() => result.current.up())
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('calendarDay', () => {
  it('タイムゾーンの暦日を返す（UTC では 15 日でも、東京では 16 日になる）', () => {
    expect(calendarDay('2026-11-15T20:00:00Z', 'UTC')).toBe('2026-11-15')
    expect(calendarDay('2026-11-15T20:00:00Z', 'Asia/Tokyo')).toBe('2026-11-16')
  })
})

describe('目盛りの日付', () => {
  it('日付をまたぐときだけ日付を出す（期間の長さではなく、またぐかどうかで決める）', () => {
    // 24 時間未満でも、日付をまたぐなら日付を出す
    expect(spansCalendarDays('2026-03-21T23:00:00Z', '2026-03-22T00:40:00Z', 'UTC')).toBe(true)
    // 24 時間ちょうどでなくても、同じ日の中なら出さない
    expect(spansCalendarDays('2026-03-22T00:00:00Z', '2026-03-22T23:59:00Z', 'UTC')).toBe(false)
    // タイムゾーンで見た日付で判定する（UTC では同じ日でも、東京では 0 時をまたぐ）
    expect(spansCalendarDays('2026-03-22T14:00:00Z', '2026-03-22T16:00:00Z', 'Asia/Tokyo')).toBe(true)
  })

  it('日付ありの目盛りには月日が入り、無しは時刻だけ', () => {
    expect(formatTick('2026-03-21T23:40:00Z', 'UTC', true)).toMatch(/3\/21/)
    expect(formatTick('2026-03-21T23:40:00Z', 'UTC', false)).not.toMatch(/\//)
  })
})
