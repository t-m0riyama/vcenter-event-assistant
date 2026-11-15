import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api'
import { VIEW_RESPONSE_EXAMPLE } from '../test/timelineViewFixtures'
import {
  postIncidentTimelineView,
  TimelineBusyError,
  TimelineRequestSupersededError,
} from './incidentTimelineView'

const BODY = { from: '2026-03-22T00:00:00Z', to: '2026-03-22T01:00:00Z' }

function json(data: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

describe('postIncidentTimelineView', () => {
  const fetchMock = vi.fn()
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('応答を zod で検証して返す', async () => {
    fetchMock.mockResolvedValueOnce(json(VIEW_RESPONSE_EXAMPLE))
    const out = await postIncidentTimelineView(BODY)
    expect(out.items).toHaveLength(2)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/incident-timeline/view')
    expect(JSON.parse(String(init.body))).toEqual(BODY)
  })

  it('503 は Retry-After 秒だけ待って 1 回だけ再試行する', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ detail: 'busy' }, 503, { 'Retry-After': '2' }))
      .mockResolvedValueOnce(json(VIEW_RESPONSE_EXAMPLE))
    const p = postIncidentTimelineView(BODY)
    await vi.advanceTimersByTimeAsync(1500)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(600)
    await expect(p).resolves.toMatchObject({ total_items: 2 })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('429 も再試行し、再試行でも混み合っていれば TimelineBusyError にする', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'Too many requests' }, 429)))
    const p = postIncidentTimelineView(BODY)
    const assertion = expect(p).rejects.toBeInstanceOf(TimelineBusyError)
    await vi.advanceTimersByTimeAsync(4000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('Retry-After が長くても待つのは 10 秒まで', async () => {
    fetchMock
      .mockResolvedValueOnce(json({}, 503, { 'Retry-After': '120' }))
      .mockResolvedValueOnce(json(VIEW_RESPONSE_EXAMPLE))
    const p = postIncidentTimelineView(BODY)
    await vi.advanceTimersByTimeAsync(10_100)
    await expect(p).resolves.toBeDefined()
  })

  it('待つ間に不要になったら再試行しない', async () => {
    fetchMock.mockResolvedValue(json({}, 503, { 'Retry-After': '1' }))
    let superseded = false
    const p = postIncidentTimelineView(BODY, () => superseded)
    const assertion = expect(p).rejects.toBeInstanceOf(TimelineRequestSupersededError)
    await vi.advanceTimersByTimeAsync(100)
    superseded = true
    await vi.advanceTimersByTimeAsync(1500)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('422 は再試行せず、サーバの detail をそのまま載せる', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'イベントの種類が多すぎて集計できません。' }, 422))
    const err = await postIncidentTimelineView(BODY).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toBe('イベントの種類が多すぎて集計できません。')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
