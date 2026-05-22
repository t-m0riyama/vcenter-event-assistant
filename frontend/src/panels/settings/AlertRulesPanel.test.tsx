/**
 * @vitest-environment happy-dom
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AlertRulesPanel } from './AlertRulesPanel'

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('AlertRulesPanel metric_threshold create', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('新規メトリクスルールの POST に host.cpu.usage_pct が含まれる', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            id: 1,
            name: 'CPU rule',
            rule_type: 'metric_threshold',
            is_enabled: true,
            alert_level: 'warning',
            config: { metric_key: 'host.cpu.usage_pct', threshold: 90 },
          },
          201,
        ),
      )
      .mockResolvedValueOnce(jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/alerts/rules', expect.any(Object))
    })

    fireEvent.click(screen.getByRole('button', { name: '新規ルール追加' }))
    fireEvent.change(screen.getByLabelText('ルール名'), { target: { value: 'CPU rule' } })
    fireEvent.change(screen.getByLabelText('タイプ'), { target: { value: 'metric_threshold' } })

    const metricInput = screen.getByLabelText('メトリクスキー') as HTMLInputElement
    expect(metricInput.value).toBe('host.cpu.usage_pct')

    fireEvent.change(screen.getByLabelText('閾値'), { target: { value: '90' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        (c) => c[0] === '/api/alerts/rules' && (c[1] as RequestInit)?.method === 'POST',
      )
      expect(postCall).toBeDefined()
      const body = JSON.parse(String((postCall![1] as RequestInit).body))
      expect(body.config.metric_key).toBe('host.cpu.usage_pct')
    })
  })
})
