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

    fireEvent.change(screen.getByLabelText('ルール名'), { target: { value: 'CPU rule' } })
    fireEvent.change(screen.getByLabelText('タイプ'), { target: { value: 'metric_threshold' } })

    const metricInput = screen.getByLabelText('メトリクスキー') as HTMLInputElement
    expect(metricInput.value).toBe('host.cpu.usage_pct')

    fireEvent.change(screen.getByLabelText('閾値'), { target: { value: '90' } })
    fireEvent.click(screen.getByRole('button', { name: '追加' }))

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

describe('AlertRulesPanel list', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const rule = {
    id: 7,
    name: 'High score',
    rule_type: 'event_score',
    is_enabled: true,
    alert_level: 'critical',
    config: { threshold: 80, cooldown_minutes: 30 },
    created_at: '2026-10-01T00:00:00Z',
  }

  it('折りたたんだ行にレベル・タイプ・条件を出し、展開して変えた内容を 1 回の PATCH で保存する', async () => {
    let current = rule
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        current = { ...current, ...JSON.parse(String(init.body)) }
        return jsonResponse(current)
      }
      return jsonResponse([current])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    const summary = await screen.findByLabelText(/^High score、クリティカル、イベントスコア、有効$/)
    expect(summary).toHaveTextContent('スコア 80 以上')
    fireEvent.click(summary)

    const save = screen.getByRole('button', { name: '保存' })
    expect(save).toBeDisabled()
    fireEvent.change(screen.getByLabelText('High score のアラートレベル'), { target: { value: 'warning' } })
    fireEvent.click(screen.getByLabelText('High score を有効にする'))
    expect(save).toBeEnabled()
    fireEvent.click(save)

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'PATCH')
      expect(patch?.[0]).toBe('/api/alerts/rules/7')
      const body = JSON.parse(String((patch![1] as RequestInit).body))
      // 変えた項目だけを送る
      expect(body).toEqual({ alert_level: 'warning', is_enabled: false })
    })
    expect(fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method === 'PATCH')).toHaveLength(1)
    await screen.findByLabelText(/^High score、警告、イベントスコア、無効$/)
  })

  it('編集中に一覧を読み直しても、変えていない項目はサーバの新しい値を出し、保存でも戻さない', async () => {
    const other = { ...rule, id: 8, name: 'Other', alert_level: 'warning' }
    let first = rule
    const patches: { url: string; body: unknown }[] = []
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        patches.push({ url, body: JSON.parse(String(init.body)) })
        // 別の利用者やインポートで、id 7 のレベルと有効が変わったことにする
        first = { ...first, alert_level: 'error', is_enabled: false }
        return jsonResponse({})
      }
      return jsonResponse([first, other])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    // id 7 の名前だけを変えて、保存しないまま
    fireEvent.click(await screen.findByLabelText(/^High score、/))
    fireEvent.change(screen.getByLabelText('High score のルール名'), { target: { value: 'High score 2' } })
    // 別のルールを保存して、一覧を読み直させる
    fireEvent.click(screen.getByLabelText(/^Other、/))
    fireEvent.change(screen.getByLabelText('Other の閾値'), { target: { value: '70' } })
    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[1])
    await screen.findByLabelText(/^High score、エラー、イベントスコア、無効$/)

    // 読み直した値が出て、編集した名前は残る
    expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('error')
    expect(screen.getByLabelText('High score を有効にする')).not.toBeChecked()
    expect(screen.getByLabelText('High score のルール名')).toHaveValue('High score 2')

    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[0])
    await waitFor(() => expect(patches).toHaveLength(2))
    expect(patches[1]).toEqual({ url: '/api/alerts/rules/7', body: { name: 'High score 2' } })
  })
})
