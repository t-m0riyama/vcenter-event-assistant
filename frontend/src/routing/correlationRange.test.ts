/** @vitest-environment happy-dom */
import { describe, expect, it } from 'vitest'
import { correlationHash, logsAroundEvent, readCorrelationRange } from './correlationRange'
import { parseAppHash } from './appHashRouting'

 describe('event/log correlation', () => {
  it('keeps the vCenter and exact UTC five-minute range in a shareable link', () => {
    const hash = logsAroundEvent('vc-1', '2026-10-02T10:00:25Z')
    window.history.replaceState(null, '', hash)
    expect(parseAppHash(hash).tab).toBe('logs')
    const range = readCorrelationRange('logs')
    expect(range).toEqual({ vcenterId: 'vc-1', from: '2026-10-02T09:55:25.000Z', to: '2026-10-02T10:05:25.000Z' })
    window.history.replaceState(null, '', correlationHash('events', range!))
    expect(parseAppHash(window.location.hash).tab).toBe('events')
    expect(readCorrelationRange('events')).toEqual(range)
  })
  it('rejects invalid or reversed ranges', () => {
    window.history.replaceState(null, '', '#/logs?vcenter_id=vc-1&from=bad&to=bad')
    expect(readCorrelationRange('logs')).toBeNull()
  })
})
