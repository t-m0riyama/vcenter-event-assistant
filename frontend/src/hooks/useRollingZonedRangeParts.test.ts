import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useRollingZonedRangeParts } from './useRollingZonedRangeParts'

describe('useRollingZonedRangeParts', () => {
  it('TZ変更時に rolling なら期間を再計算する', () => {
    const { result, rerender } = renderHook(
      ({ tz }: { tz: string }) => useRollingZonedRangeParts(tz),
      { initialProps: { tz: 'UTC' } },
    )
    const utcParts = { ...result.current.rangeParts }
    rerender({ tz: 'Asia/Tokyo' })
    expect(result.current.rangeParts).not.toEqual(utcParts)
  })

  it('手入力後は TZ 変更で上書きしない', () => {
    const { result, rerender } = renderHook(
      ({ tz }: { tz: string }) => useRollingZonedRangeParts(tz),
      { initialProps: { tz: 'UTC' } },
    )
    const manualParts = {
      fromDate: '2026-01-01',
      fromTime: '08:00',
      toDate: '2026-01-02',
      toTime: '09:00',
    }
    act(() => {
      result.current.setRangeParts(manualParts)
    })
    rerender({ tz: 'Asia/Tokyo' })
    expect(result.current.rangeParts).toEqual(manualParts)
  })

  it('要約は既定で「直近24時間」、手入力で日付、クイックで「直近 N」に戻る', () => {
    const { result, rerender } = renderHook(
      ({ tz }: { tz: string }) => useRollingZonedRangeParts(tz),
      { initialProps: { tz: 'UTC' } },
    )
    expect(result.current.rangeDisplayLabel).toBe('直近24時間')
    act(() => {
      result.current.setRangeParts({
        fromDate: '2026-01-01',
        fromTime: '08:00',
        toDate: '2026-01-02',
        toTime: '09:00',
      })
    })
    expect(result.current.rangeDisplayLabel).toBe('2026-01-01 ～ 2026-01-02')
    act(() => {
      result.current.applyRollingPreset(7 * 86400000)
    })
    expect(result.current.rangeDisplayLabel).toBe('直近 7 日')
    // ローリングに戻ったので、TZ を変えると期間を計算し直す。
    const rollingParts = { ...result.current.rangeParts }
    rerender({ tz: 'Asia/Tokyo' })
    expect(result.current.rangeParts).not.toEqual(rollingParts)
  })
})
