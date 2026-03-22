import { describe, expect, it } from 'vitest'
import {
  xAxisBottomMarginForWidth,
  xAxisMinTickGapForWidth,
  xAxisTickCountForWidth,
} from './chartXAxisLayout'

describe('xAxisBottomMarginForWidth', () => {
  it('狭い幅では下余白を広くする', () => {
    expect(xAxisBottomMarginForWidth(320)).toBeGreaterThan(xAxisBottomMarginForWidth(800))
  })

  it('未計測時は中間付近', () => {
    expect(xAxisBottomMarginForWidth(0)).toBe(58)
  })

  it('52〜68 の範囲に収まる', () => {
    expect(xAxisBottomMarginForWidth(320)).toBeGreaterThanOrEqual(52)
    expect(xAxisBottomMarginForWidth(320)).toBeLessThanOrEqual(68)
  })
})

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
