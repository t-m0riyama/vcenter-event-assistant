import { describe, expect, it } from 'vitest'
import {
  buildMetricsChartModel,
  formatMetricChartSeriesLegendName,
  hostMetricSeriesDataKey,
  isDatastoreMetricKey,
  isHostMetricKey,
} from './buildMetricsChartModel'
import { bucketEpochUtcSec } from './metricCsv'
import type { MetricPoint } from './normalizeMetricSeriesResponse'

const basePoint = (
  overrides: Partial<MetricPoint> & Pick<MetricPoint, 'sampled_at' | 'value' | 'entity_moid'>,
): MetricPoint => ({
  metric_key: 'host.cpu.usage_pct',
  vcenter_id: '00000000-0000-0000-0000-000000000001',
  entity_name: 'esxi-a',
  ...overrides,
})

describe('isHostMetricKey', () => {
  it('returns true for host.* keys', () => {
    expect(isHostMetricKey('host.cpu.usage_pct')).toBe(true)
    expect(isHostMetricKey('  host.mem.usage_pct')).toBe(true)
  })
  it('returns false for other keys', () => {
    expect(isHostMetricKey('vm.cpu')).toBe(false)
    expect(isHostMetricKey('')).toBe(false)
  })
})

describe('isDatastoreMetricKey', () => {
  it('returns true for datastore.* keys', () => {
    expect(isDatastoreMetricKey('datastore.space.used_bytes')).toBe(true)
    expect(isDatastoreMetricKey('  datastore.space.used_pct')).toBe(true)
  })
  it('returns false for other keys', () => {
    expect(isDatastoreMetricKey('host.cpu.usage_pct')).toBe(false)
    expect(isDatastoreMetricKey('')).toBe(false)
  })
})

describe('hostMetricSeriesDataKey', () => {
  it('prefixes and sanitizes moid', () => {
    expect(hostMetricSeriesDataKey('host-21')).toBe('m_host_21')
    expect(hostMetricSeriesDataKey('a.b-c')).toBe('m_a_b_c')
  })
  it('includes vcenter id when provided', () => {
    expect(hostMetricSeriesDataKey('host-21', 'vc-1')).toBe('m_host_21__vc_vc_1')
  })
})

describe('buildMetricsChartModel', () => {
  it('single mode: maps points to v and evCount from bucket', () => {
    const sampled = '2025-01-01T00:00:00'
    const points: MetricPoint[] = [
      basePoint({
        metric_key: 'other.metric',
        sampled_at: sampled,
        value: 10,
        entity_moid: 'x',
        entity_name: 'n',
      }),
    ]
    const count = new Map<number, number>([[bucketEpochUtcSec(sampled, 300), 3]])
    const r = buildMetricsChartModel('other.metric', points, 300, true, count)
    expect(r.mode).toBe('single')
    if (r.mode !== 'single') throw new Error('expected single')
    expect(r.rows).toHaveLength(1)
    expect(r.rows[0]).toMatchObject({ v: 10, evCount: 3 })
    expect(r.metricSeries).toEqual([{ dataKey: 'v', legendName: '' }])
  })

  it('host mode: splits series by entity_moid and merges same timestamp into one row', () => {
    const t = '2025-01-01T12:00:00Z'
    const points: MetricPoint[] = [
      basePoint({
        sampled_at: t,
        value: 11,
        entity_moid: 'host-1',
        entity_name: 'ESXi-1',
      }),
      basePoint({
        sampled_at: t,
        value: 22,
        entity_moid: 'host-2',
        entity_name: 'ESXi-2',
      }),
      basePoint({
        sampled_at: '2025-01-01T13:00:00Z',
        value: 33,
        entity_moid: 'host-1',
        entity_name: 'ESXi-1',
      }),
    ]
    const r = buildMetricsChartModel('host.cpu.usage_pct', points, 300, false, new Map())
    expect(r.mode).toBe('host')
    if (r.mode !== 'host') throw new Error('expected host')
    expect(r.metricSeries).toHaveLength(2)
    expect(r.metricSeries.map((s) => s.dataKey).sort()).toEqual(['m_host_1', 'm_host_2'])
    expect(r.rows).toHaveLength(2)
    const k1 = hostMetricSeriesDataKey('host-1')
    const k2 = hostMetricSeriesDataKey('host-2')
    const row0 = r.rows.find((row) => row.tMs === Date.parse(t))
    expect(row0?.[k1]).toBe(11)
    expect(row0?.[k2]).toBe(22)
  })

  it('host mode: disambiguates duplicate entity_name in legend', () => {
    const t = '2025-01-01T12:00:00Z'
    const points: MetricPoint[] = [
      basePoint({
        sampled_at: t,
        value: 1,
        entity_moid: 'a',
        entity_name: 'dup',
      }),
      basePoint({
        sampled_at: t,
        value: 2,
        entity_moid: 'b',
        entity_name: 'dup',
      }),
    ]
    const r = buildMetricsChartModel('host.mem.usage_pct', points, 300, false, new Map())
    if (r.mode !== 'host') throw new Error('expected host')
    const names = new Set(r.metricSeries.map((s) => s.legendName))
    expect(names.has('dup (a)')).toBe(true)
    expect(names.has('dup (b)')).toBe(true)
  })

  it('host mode: splits by vcenter when multiple vcenters are present', () => {
    const t = '2025-01-01T12:00:00Z'
    const vc1 = '00000000-0000-0000-0000-000000000001'
    const vc2 = '00000000-0000-0000-0000-000000000002'
    const points: MetricPoint[] = [
      basePoint({
        sampled_at: t,
        value: 11,
        entity_moid: 'host-1',
        entity_name: 'ESXi-1',
        vcenter_id: vc1,
      }),
      basePoint({
        sampled_at: t,
        value: 22,
        entity_moid: 'host-1',
        entity_name: 'ESXi-1',
        vcenter_id: vc2,
      }),
    ]
    const vcenterNameById = new Map([
      [vc1, 'VC-A'],
      [vc2, 'VC-B'],
    ])
    const r = buildMetricsChartModel(
      'host.cpu.usage_pct',
      points,
      300,
      false,
      new Map(),
      vcenterNameById,
      true,
    )
    if (r.mode !== 'host') throw new Error('expected host')
    expect(r.metricSeries).toHaveLength(2)
    expect(r.metricSeries.map((s) => s.vcenterLegendPrefix).sort()).toEqual(['VC-A', 'VC-B'])
    expect(
      r.metricSeries.map((s) => formatMetricChartSeriesLegendName(s, '全て')).sort(),
    ).toEqual(['VC-A / ESXi-1', 'VC-B / ESXi-1'])
    const k1 = hostMetricSeriesDataKey('host-1', vc1)
    const k2 = hostMetricSeriesDataKey('host-1', vc2)
    expect(r.rows).toHaveLength(1)
    expect(r.rows[0]?.[k1]).toBe(11)
    expect(r.rows[0]?.[k2]).toBe(22)
  })

  it('uses vcenter prefix in legend when splitSeriesByVcenter is true even for single vcenter data', () => {
    const t = '2025-01-01T12:00:00Z'
    const vc1 = '00000000-0000-0000-0000-000000000001'
    const points: MetricPoint[] = [
      basePoint({
        sampled_at: t,
        value: 11,
        entity_moid: 'ds-1',
        entity_name: 'DS-1',
        vcenter_id: vc1,
      }),
    ]
    const vcenterNameById = new Map([[vc1, 'VC-A']])
    const r = buildMetricsChartModel(
      'datastore.space.used_pct',
      points,
      300,
      false,
      new Map(),
      vcenterNameById,
      true,
    )
    if (r.mode !== 'host') throw new Error('expected host')
    expect(formatMetricChartSeriesLegendName(r.metricSeries[0], '全て')).toBe('VC-A / DS-1')
  })

  it('datastore mode: splits series by entity_moid and merges same timestamp into one row', () => {
    const t = '2025-01-01T12:00:00Z'
    const points: MetricPoint[] = [
      basePoint({
        metric_key: 'datastore.space.used_pct',
        sampled_at: t,
        value: 11,
        entity_moid: 'ds-1',
        entity_name: 'DS-1',
      }),
      basePoint({
        metric_key: 'datastore.space.used_pct',
        sampled_at: t,
        value: 22,
        entity_moid: 'ds-2',
        entity_name: 'DS-2',
      }),
      basePoint({
        metric_key: 'datastore.space.used_pct',
        sampled_at: '2025-01-01T13:00:00Z',
        value: 33,
        entity_moid: 'ds-1',
        entity_name: 'DS-1',
      }),
    ]
    const r = buildMetricsChartModel('datastore.space.used_pct', points, 300, false, new Map())
    expect(r.mode).toBe('host')
    if (r.mode !== 'host') throw new Error('expected host')
    expect(r.metricSeries).toHaveLength(2)
    expect(r.metricSeries.map((s) => s.dataKey).sort()).toEqual(['m_ds_1', 'm_ds_2'])
    expect(r.rows).toHaveLength(2)
    const k1 = hostMetricSeriesDataKey('ds-1')
    const k2 = hostMetricSeriesDataKey('ds-2')
    const row0 = r.rows.find((row) => row.tMs === Date.parse(t))
    expect(row0?.[k1]).toBe(11)
    expect(row0?.[k2]).toBe(22)
  })
})
