import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildLogExportUrl, buildLogListSearchParams, downloadLogCsv, type LogFilters } from './logExport'

const filters: LogFilters = {
  vcenter_id: 'vc-1', source_id: 'esxi-1', log_kind: 'vmkernel', severity: 'error',
  message_contains: '日本語 & 100%', from: '2026-10-02T09:55:25Z', to: '2026-10-02T10:05:25Z',
}

afterEach(() => vi.restoreAllMocks())

describe('log export', () => {
  it('encodes filters and time zone without pagination', () => {
    const url = new URL(buildLogExportUrl(filters, 'Asia/Tokyo'), 'http://test')
    expect(url.pathname).toBe('/api/logs/export.csv')
    expect(Object.fromEntries(url.searchParams)).toEqual({ ...filters, time_zone: 'Asia/Tokyo' })
    expect(Object.fromEntries(buildLogListSearchParams(filters, 50, 100)))
      .toEqual({ ...filters, limit: '50', offset: '100' })
  })

  it('omits empty filters', () => {
    const url = new URL(buildLogExportUrl({ ...filters, source_id: '', from: undefined }, 'UTC'), 'http://test')
    expect(url.searchParams.has('source_id')).toBe(false)
    expect(url.searchParams.has('from')).toBe(false)
  })

  it('delegates to a native download link and removes it after dispatch', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(document.body.contains(this)).toBe(true)
    })
    const url = buildLogExportUrl(filters, 'UTC')
    downloadLogCsv(url)
    expect(click).toHaveBeenCalledTimes(1)
    const link = click.mock.contexts[0] as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe(url)
    expect(link.hasAttribute('download')).toBe(true)
    expect(link.target).toBe('_blank')
    expect(link.rel).toBe('noopener')
    expect(document.body.contains(link)).toBe(false)
  })
})
