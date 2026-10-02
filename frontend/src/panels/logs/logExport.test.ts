import { describe, expect, it, vi } from 'vitest'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { escapeCsvField } from '../../metrics/metricCsv'
import { buildLogExportFilename, fetchAllLogsForExport, logRowsToCsv, type LogFilters, type LogRow } from './logExport'

const row: LogRow = {
  id: 1, vcenter_id: 'vc-1', source_id: 'esxi-1', host: 'esxi.local', log_kind: 'vmkernel',
  file_generation: 'gen-1', byte_offset: 12, occurred_at: null,
  collected_at: '2026-10-02T10:01:00Z', effective_at: '2026-10-02T10:00:00Z', severity: null,
  message: '日本語, "error"\n stack trace',
}
const filters: LogFilters = {
  vcenter_id: 'vc-1', source_id: 'esxi-1', log_kind: 'vmkernel', severity: 'error',
  message_contains: 'Storage', from: '2026-10-02T09:55:25Z', to: '2026-10-02T10:05:25Z',
}

describe('log export', () => {
  it('fetches every page in API order and preserves all filters', async () => {
    const first = Array.from({ length: 200 }, (_, i) => ({ ...row, id: 201 - i }))
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: first, total: 201 })
      .mockResolvedValueOnce({ items: [row], total: 201 })
    expect(await fetchAllLogsForExport(fetchPage, filters)).toEqual([...first, row])
    expect(fetchPage).toHaveBeenCalledTimes(2)
    fetchPage.mock.calls.forEach(([params], i) => {
      expect(Object.fromEntries(params)).toEqual({ ...filters, limit: '200', offset: String(i * 200) })
    })
  })

  it('stops on an empty page even if total still indicates more rows', async () => {
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: [row], total: 10 })
      .mockResolvedValueOnce({ items: [], total: 10 })
    expect(await fetchAllLogsForExport(fetchPage, filters)).toEqual([row])
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it('rejects failed requests and malformed pages instead of returning partial rows', async () => {
    const fetchPage = vi.fn().mockResolvedValueOnce({ items: [row], total: 10 })
      .mockRejectedValueOnce(new Error('offline'))
    await expect(fetchAllLogsForExport(fetchPage, filters)).rejects.toThrow('offline')
    await expect(fetchAllLogsForExport(async () => ({ items: [{}], total: 1 }), filters)).rejects.toThrow()
  })

  it('exports all detail columns with escaped full text, nulls and selected time zone', () => {
    const timeZone = 'Asia/Tokyo'
    const csv = logRowsToCsv([row], new Map([['vc-1', 'Lab,東京']]), timeZone)
    const time = (iso: string) => escapeCsvField(formatIsoInTimeZone(iso, timeZone))
    expect(csv).toBe(
      'id,vcenter_id,vcenter_name,source_id,host,log_kind,effective_at,occurred_at,collected_at,severity,message,file_generation,byte_offset\r\n'
      + `1,vc-1,"Lab,東京",esxi-1,esxi.local,vmkernel,${time(row.effective_at)},,${time(row.collected_at)},,"日本語, ""error""\n stack trace",gen-1,12\r\n`,
    )
    expect(csv.startsWith('\uFEFF')).toBe(false)
    expect(logRowsToCsv([{ ...row, occurred_at: row.effective_at, severity: 'error' }], new Map(), 'UTC'))
      .toContain(`1,vc-1,vc-1,esxi-1,esxi.local,vmkernel,${escapeCsvField(formatIsoInTimeZone(row.effective_at, 'UTC'))},${escapeCsvField(formatIsoInTimeZone(row.effective_at, 'UTC'))},`)
    expect(logRowsToCsv([], new Map(), 'UTC')).toBe(csv.slice(0, csv.indexOf('\r\n') + 2))
  })

  it('uses the logs filename prefix and timestamp', () => {
    expect(buildLogExportFilename(new Date(2026, 9, 3, 12, 34, 56))).toBe('logs-20261003-123456.csv')
  })
})
