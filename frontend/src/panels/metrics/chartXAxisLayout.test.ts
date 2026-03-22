import { describe, expect, it } from 'vitest'
import { xAxisMinTickGapForWidth, xAxisTickCountForWidth } from './chartXAxisLayout'

describe('xAxisMinTickGapForWidth', () => {
  it('狭い幅では目盛り間隔を広くする', () => {
    expect(xAxisMinTickGapForWidth(320)).toBeGreaterThan(xAxisMinTickGapForWidth(800))
  })

  it('未計測時は中間付近の値', () => {
    expect(xAxisMinTickGapForWidth(0)).toBe(40)
  })
})

describe('xAxisTickCountForWidth', () => {
  it('幅に応じて 4〜8 の範囲に収まる', () => {
    expect(xAxisTickCountForWidth(300)).toBeGreaterThanOrEqual(4)
    expect(xAxisTickCountForWidth(1200)).toBeLessThanOrEqual(8)
  })

  it('未計測時は 6', () => {
    expect(xAxisTickCountForWidth(0)).toBe(6)
  })
})
