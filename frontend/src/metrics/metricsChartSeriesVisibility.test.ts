import { describe, expect, it } from 'vitest'
import {
  buildMetricsChartSeriesIdentityKey,
  legendDataKeyToString,
  toggleHiddenSeriesDataKey,
} from './metricsChartSeriesVisibility'

describe('toggleHiddenSeriesDataKey', () => {
  it('空集合から dataKey をトグルすると非表示に追加され、もう一度トグルで元に戻る', () => {
    const hidden = toggleHiddenSeriesDataKey(new Set(), 'host-1')
    expect([...hidden].sort()).toEqual(['host-1'])
    const hidden2 = toggleHiddenSeriesDataKey(hidden, 'host-1')
    expect([...hidden2]).toEqual([])
  })

  it('入力の Set は破壊しない', () => {
    const original = new Set<string>(['a'])
    const next = toggleHiddenSeriesDataKey(original, 'b')
    expect(original.has('b')).toBe(false)
    expect([...next].sort()).toEqual(['a', 'b'])
  })
})

describe('legendDataKeyToString', () => {
  it('文字列の dataKey はそのまま返す', () => {
    expect(legendDataKeyToString('v')).toBe('v')
    expect(legendDataKeyToString('host-moid-1')).toBe('host-moid-1')
  })

  it('数値の dataKey は文字列化する', () => {
    expect(legendDataKeyToString(0)).toBe('0')
    expect(legendDataKeyToString(42)).toBe('42')
  })

  it('null と undefined は null を返す', () => {
    expect(legendDataKeyToString(null)).toBe(null)
    expect(legendDataKeyToString(undefined)).toBe(null)
  })
})

describe('buildMetricsChartSeriesIdentityKey', () => {
  it('metricSeriesDataKeys の順序が違っても同じ集合なら同一キーになる', () => {
    const a = buildMetricsChartSeriesIdentityKey({
      metricKey: 'cpu.usage',
      chartMode: 'host',
      metricSeriesDataKeys: ['z', 'a', 'm'],
      showEventLine: true,
    })
    const b = buildMetricsChartSeriesIdentityKey({
      metricKey: 'cpu.usage',
      chartMode: 'host',
      metricSeriesDataKeys: ['a', 'm', 'z'],
      showEventLine: true,
    })
    expect(a).toBe(b)
  })

  it('metricKey が変わればキーが変わる', () => {
    const a = buildMetricsChartSeriesIdentityKey({
      metricKey: 'a',
      chartMode: 'host',
      metricSeriesDataKeys: ['x'],
      showEventLine: false,
    })
    const b = buildMetricsChartSeriesIdentityKey({
      metricKey: 'b',
      chartMode: 'host',
      metricSeriesDataKeys: ['x'],
      showEventLine: false,
    })
    expect(a).not.toBe(b)
  })

  it('showEventLine が変わればキーが変わる', () => {
    const a = buildMetricsChartSeriesIdentityKey({
      metricKey: 'k',
      chartMode: 'single',
      metricSeriesDataKeys: ['v'],
      showEventLine: false,
    })
    const b = buildMetricsChartSeriesIdentityKey({
      metricKey: 'k',
      chartMode: 'single',
      metricSeriesDataKeys: ['v'],
      showEventLine: true,
    })
    expect(a).not.toBe(b)
  })
})
