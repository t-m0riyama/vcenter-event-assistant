import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api'
import { emptyViewResponse, LOG_ITEM_EXAMPLE, METRIC_ITEM_EXAMPLE, METRIC_ITEM_LEGACY_EXAMPLE, VIEW_RESPONSE_EXAMPLE } from '../test/timelineViewFixtures'
import {
  postIncidentTimelineView,
  TimelineBusyError,
  TimelineRateLimitedError,
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

  it('メトリクスの ref の構造化した値と omitted_sources を読む', async () => {
    fetchMock.mockResolvedValueOnce(
      json(
        emptyViewResponse({
          items: [METRIC_ITEM_EXAMPLE, LOG_ITEM_EXAMPLE],
          omitted_sources: [{ source: 'log', reason: 'too_many_rows' }],
        }),
      ),
    )
    const out = await postIncidentTimelineView(BODY)
    expect(out.items[0].ref).toMatchObject({
      threshold_pct: 80,
      peak_value: 92.5,
      peak_at_utc: '2026-03-22T00:10:00Z',
      sample_count: 3,
      continues_from_before: false,
      continues_after: false,
    })
    expect(out.omitted_sources).toEqual([{ source: 'log', reason: 'too_many_rows' }])
  })

  it('新しい項目が無い応答（古いサーバ）も受け付け、omitted_sources は空になる', async () => {
    fetchMock.mockResolvedValueOnce(json(emptyViewResponse({ items: [METRIC_ITEM_LEGACY_EXAMPLE] })))
    const out = await postIncidentTimelineView(BODY)
    expect(out.omitted_sources).toEqual([])
    expect(out.items[0].ref.peak_value).toBeUndefined()
    expect(out.items[0].ref.continues_after).toBeUndefined()
    expect(out.items[0].ref.metric_key).toBe('host.cpu.usage_pct')
  })

  it('構造化した値が null でも受け付ける', async () => {
    fetchMock.mockResolvedValueOnce(
      json(
        emptyViewResponse({
          items: [{ ...METRIC_ITEM_EXAMPLE, ref: { metric_key: 'host.cpu.usage_pct', peak_value: null, peak_at_utc: null } }],
        }),
      ),
    )
    await expect(postIncidentTimelineView(BODY)).resolves.toBeDefined()
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

  it('503 が再試行でも続けば TimelineBusyError にする', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'busy' }, 503)))
    const p = postIncidentTimelineView(BODY)
    const assertion = expect(p).rejects.toBeInstanceOf(TimelineBusyError)
    await vi.advanceTimersByTimeAsync(4000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('429 は再試行せず、専用のエラー（レート制限）にする', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json({ detail: 'Too many requests' }, 429)))
    const err = await postIncidentTimelineView(BODY).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(TimelineRateLimitedError)
    expect((err as Error).message).toContain('短時間に操作が多すぎます')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('Retry-After が長くても待つのは 10 秒まで', async () => {
    fetchMock
      .mockResolvedValueOnce(json({}, 503, { 'Retry-After': '120' }))
      .mockResolvedValueOnce(json(VIEW_RESPONSE_EXAMPLE))
    const p = postIncidentTimelineView(BODY)
    await vi.advanceTimersByTimeAsync(10_100)
    await expect(p).resolves.toBeDefined()
  })

  it('待つ間に中断されたら、待ちきらずに取りやめて再試行しない', async () => {
    fetchMock.mockResolvedValue(json({}, 503, { 'Retry-After': '10' }))
    const abort = new AbortController()
    const p = postIncidentTimelineView(BODY, abort.signal)
    const assertion = expect(p).rejects.toBeInstanceOf(TimelineRequestSupersededError)
    await vi.advanceTimersByTimeAsync(100)
    abort.abort()
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('422 の検証エラー（detail が配列）は「項目: 理由」に整える', async () => {
    fetchMock.mockResolvedValueOnce(
      json(
        {
          detail: [
            { loc: ['body', 'entity'], msg: 'String should have at most 256 characters', type: 'string_too_long' },
            { loc: ['body'], msg: 'Value error, time range must not exceed 90 days', type: 'value_error' },
          ],
        },
        422,
      ),
    )
    await expect(postIncidentTimelineView(BODY)).rejects.toThrow(
      'entity: String should have at most 256 characters / Value error, time range must not exceed 90 days',
    )
  })

  it('422 は再試行せず、サーバの detail をそのまま載せる', async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: 'イベントの種類が多すぎて集計できません。' }, 422))
    const err = await postIncidentTimelineView(BODY).catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).message).toBe('イベントの種類が多すぎて集計できません。')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
