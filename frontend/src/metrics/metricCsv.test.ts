import { describe, expect, it } from 'vitest'

import { escapeCsvField, metricPointsToCsv } from './metricCsv'
import type { MetricPoint } from './normalizeMetricSeriesResponse'

describe('escapeCsvField', () => {
  it('returns plain string when no special chars', () => {
    expect(escapeCsvField('abc')).toBe('abc')
  })

  it('wraps and escapes quotes when needed', () => {
    expect(escapeCsvField('say "hi"')).toBe('"say ""hi"""')
  })

  it('wraps when comma present', () => {
    expect(escapeCsvField('a,b')).toBe('"a,b"')
  })

  it('wraps on newline', () => {
    expect(escapeCsvField('a\nb')).toBe('"a\nb"')
  })
})

describe('metricPointsToCsv', () => {
  const base: MetricPoint = {
    sampled_at: '2024-01-01T00:00:00Z',
    value: 1.5,
    entity_name: 'host-a',
    entity_moid: 'moid-1',
    metric_key: 'host.cpu.usage_pct',
    vcenter_id: '00000000-0000-0000-0000-000000000001',
  }

  it('outputs header and CRLF line endings', () => {
    const csv = metricPointsToCsv([])
    expect(csv).toBe(
      'sampled_at,value,entity_name,entity_moid,metric_key,vcenter_id\r\n',
    )
  })

  it('serializes one row', () => {
    const csv = metricPointsToCsv([base])
    expect(csv).toBe(
      'sampled_at,value,entity_name,entity_moid,metric_key,vcenter_id\r\n' +
        '2024-01-01T00:00:00Z,1.5,host-a,moid-1,host.cpu.usage_pct,00000000-0000-0000-0000-000000000001\r\n',
    )
  })

  it('escapes fields with commas in entity_name', () => {
    const csv = metricPointsToCsv([{ ...base, entity_name: 'h,ost' }])
    expect(csv).toContain('"h,ost"')
  })
})
