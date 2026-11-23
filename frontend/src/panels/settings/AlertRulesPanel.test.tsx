/**
 * @vitest-environment happy-dom
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AlertRulesPanel } from './AlertRulesPanel'

function jsonResponse(data: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
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

  const initialRevision = '81d535f3-9d2b-4050-a276-284566833a48'
  const recentRevision = '24cc5d8e-b239-4250-80fb-e6478ff2c8bc'

  const rule = {
    id: 7,
    name: 'High score',
    rule_type: 'event_score',
    is_enabled: true,
    alert_level: 'critical',
    config: { threshold: 80, cooldown_minutes: 30 },
    created_at: '2026-10-01T00:00:00Z',
    revision: initialRevision,
  }

  it('折りたたんだ行にレベル・タイプ・条件を出し、展開して変えた内容を 1 回の PATCH で保存する', async () => {
    let current = rule
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        current = { ...current, ...JSON.parse(String(init.body)), revision: recentRevision }
        return jsonResponse(current)
      }
      return jsonResponse([current])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    const summary = await screen.findByLabelText(/^High score、クリティカル、イベントスコア、有効$/)
    expect(summary).toHaveTextContent('スコア 80 以上')
    fireEvent.click(summary)

    expect(screen.getByLabelText(
      'High score の再通知間隔（分）。同じイベント種別が続く場合でも、メールはおおよそこの間隔で1通まで',
    )).toHaveValue(30)
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
      expect(body).toEqual({ revision: initialRevision, alert_level: 'warning', is_enabled: false })
    })
    expect(fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method === 'PATCH')).toHaveLength(1)
    await screen.findByLabelText(/^High score、警告、イベントスコア、無効$/)
  })

  it('編集中に一覧を読み直しても、変えていない項目はサーバの新しい値を出し、保存でも戻さない', async () => {
    let other = { ...rule, id: 8, name: 'Other', alert_level: 'warning' }
    let first = rule
    const patches: { url: string; body: unknown }[] = []
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        patches.push({ url, body })
        if (url.endsWith('/7')) {
          first = { ...first, ...body, revision: '2c888af0-4179-4844-9349-0033b26efa32' }
          return jsonResponse(first)
        }
        // 別の利用者やインポートで、id 7 のレベルと有効が変わったことにする
        first = { ...first, alert_level: 'error', is_enabled: false, revision: recentRevision }
        other = { ...other, ...body, revision: recentRevision }
        return jsonResponse(other)
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
    const refreshedRow = (await screen.findByLabelText(/^High score、エラー、イベントスコア、無効$/)).closest('li')!

    // 読み直した値が出て、編集した名前は残る
    expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('error')
    expect(screen.getByLabelText('High score を有効にする')).not.toBeChecked()
    expect(screen.getByLabelText('High score のルール名')).toHaveValue('High score 2')

    const save = within(refreshedRow).getByRole('button', { name: '保存' })
    await waitFor(() => expect(save).toBeEnabled())
    fireEvent.click(save)
    await waitFor(() => expect(patches).toHaveLength(2))
    expect(patches[1]).toEqual({ url: '/api/alerts/rules/7', body: { revision: recentRevision, name: 'High score 2' } })
  })

  it('削除したルールの id が使い回されても、消したルールの編集を新しいルールに重ねない', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let list: (typeof rule)[] = [rule]
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'DELETE') {
        // 削除の後、別のルールが同じ id 7 で作られたことにする
        list = [{ ...rule, name: 'New rule', alert_level: 'warning', created_at: '2026-10-10T00:00:00Z' }]
        return new Response(null, { status: 204 })
      }
      return jsonResponse(list)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    fireEvent.click(await screen.findByLabelText(/^High score、/))
    fireEvent.change(screen.getByLabelText('High score のルール名'), { target: { value: 'Edited' } })
    fireEvent.change(screen.getByLabelText('High score のアラートレベル'), { target: { value: 'error' } })
    fireEvent.click(screen.getByRole('button', { name: '削除' }))

    fireEvent.click(await screen.findByLabelText(/^New rule、警告、/))
    expect(screen.getByLabelText('New rule のルール名')).toHaveValue('New rule')
    expect(screen.getByLabelText('New rule のアラートレベル')).toHaveValue('warning')
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
  })

  it('元の値に戻した項目は下書きに残さず、後で読み直した新しい値を上書きしない', async () => {
    let other = { ...rule, id: 8, name: 'Other', alert_level: 'warning' }
    let first = rule
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        first = { ...first, alert_level: 'error', revision: recentRevision }
        other = { ...other, ...JSON.parse(String(init.body)), revision: recentRevision }
        return jsonResponse(other)
      }
      return jsonResponse([first, other])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    // id 7 のレベルを変えて、元のクリティカルに戻す
    fireEvent.click(await screen.findByLabelText(/^High score、/))
    const level = screen.getByLabelText('High score のアラートレベル')
    fireEvent.change(level, { target: { value: 'warning' } })
    fireEvent.change(level, { target: { value: 'critical' } })
    // 別のルールを保存して読み直させる（その間に id 7 のレベルがエラーに変わる）
    fireEvent.click(screen.getByLabelText(/^Other、/))
    fireEvent.change(screen.getByLabelText('Other の閾値'), { target: { value: '70' } })
    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[1])
    await screen.findByLabelText(/^High score、エラー、/)

    expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('error')
    expect(screen.getAllByRole('button', { name: '保存' })[0]).toBeDisabled()
  })

  it('変えた項目が編集中にサーバでも変わったら、知らせて保存を止め、破棄して読み直せる', async () => {
    let other = { ...rule, id: 8, name: 'Other', alert_level: 'warning' }
    let first = rule
    const patches: unknown[] = []
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        patches.push(body)
        // 同じ時期に、id 7 のレベルがほかの操作でエラーに変わる
        first = { ...first, alert_level: 'error', revision: recentRevision }
        other = { ...other, ...body, revision: recentRevision }
        return jsonResponse(other)
      }
      return jsonResponse([first, other])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<AlertRulesPanel onError={vi.fn()} />)

    fireEvent.click(await screen.findByLabelText(/^High score、/))
    fireEvent.change(screen.getByLabelText('High score のアラートレベル'), { target: { value: 'warning' } })
    fireEvent.click(screen.getByLabelText(/^Other、/))
    fireEvent.change(screen.getByLabelText('Other の閾値'), { target: { value: '70' } })
    fireEvent.click(screen.getAllByRole('button', { name: '保存' })[1])

    await screen.findByLabelText(/^High score、エラー、イベントスコア、有効、ほかの操作で変更あり$/)
    expect(screen.getByRole('alert')).toHaveTextContent('上書きを防ぐため保存できません')
    // 利用者の値はそのまま見えるが、保存はできない
    expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('warning')
    expect(screen.getAllByRole('button', { name: '保存' })[0]).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '編集を破棄して読み直す' }))
    await waitFor(() => expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('error'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(patches).toHaveLength(1)
  })

  it('版不一致で保存を止め、読み直しに失敗しても下書きを保持し、新しい版で再編集できる', async () => {
    const onError = vi.fn()
    const patches: unknown[] = []
    let listRequests = 0
    let current = rule
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        patches.push(body)
        if (patches.length === 1) {
          current = { ...rule, alert_level: 'error', revision: recentRevision }
          return jsonResponse({ detail: 'Alert rule has changed' }, 409, { 'X-VEA-Error-Code': 'alert_rule_stale' })
        }
        current = { ...current, ...body, revision: '2c888af0-4179-4844-9349-0033b26efa32' }
        return jsonResponse(current)
      }
      listRequests++
      if (listRequests === 2) return jsonResponse({ detail: 'offline' }, 500)
      return jsonResponse([current])
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AlertRulesPanel onError={onError} />)

    fireEvent.click(await screen.findByLabelText(/^High score、/))
    const name = screen.getByLabelText('High score のルール名')
    fireEvent.change(name, { target: { value: 'My draft' } })
    const save = screen.getByRole('button', { name: '保存' })
    fireEvent.click(save)
    expect(save).toBeDisabled()
    fireEvent.click(save)
    const reload = await screen.findByRole('button', { name: '編集を破棄して読み直す' })
    expect(name).toHaveValue('My draft')
    expect(patches).toEqual([{ revision: initialRevision, name: 'My draft' }])

    fireEvent.click(reload)
    await waitFor(() => expect(reload).toBeEnabled())
    expect(name).toHaveValue('My draft')
    expect(save).toBeDisabled()
    expect(onError).toHaveBeenLastCalledWith(expect.any(String))

    fireEvent.click(reload)
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(name).toHaveValue('High score')
    expect(screen.getByLabelText('High score のアラートレベル')).toHaveValue('error')
    fireEvent.change(name, { target: { value: 'New edit' } })
    fireEvent.click(save)
    await screen.findByLabelText(/^New edit、エラー、/)
    expect(patches[1]).toEqual({ revision: recentRevision, name: 'New edit' })
  })

  it('名前重複の 409 では名前を直して再保存できる', async () => {
    const onError = vi.fn()
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'PATCH') {
        return jsonResponse({ detail: 'Alert rule with this name already exists' }, 409)
      }
      return jsonResponse([rule])
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AlertRulesPanel onError={onError} />)

    fireEvent.click(await screen.findByLabelText(/^High score、/))
    const name = screen.getByLabelText('High score のルール名')
    fireEvent.change(name, { target: { value: 'Duplicate' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Alert rule with this name already exists'))
    expect(name).toHaveValue('Duplicate')
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: '編集を破棄して読み直す' })).not.toBeInTheDocument()
  })

  it('保存直後の一覧取得に失敗しても、古い応答で巻き戻らず次の版で保存できる', async () => {
    const onError = vi.fn()
    const patches: unknown[] = []
    let current = rule
    const other = { ...rule, id: 8, name: 'Other' }
    let reads = 0
    let finishOldRead!: (response: Response) => void
    const oldRead = new Promise<Response>((resolve) => { finishOldRead = resolve })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
      if (init?.method === 'POST') return jsonResponse(other, 201)
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        patches.push(body)
        const revision = patches.length === 1 ? recentRevision : '2c888af0-4179-4844-9349-0033b26efa32'
        current = { ...current, ...body, revision }
        return jsonResponse(current)
      }
      reads++
      if (reads === 2) return oldRead
      if (reads === 3) return jsonResponse({ detail: 'offline' }, 500)
      return jsonResponse(reads === 1 ? [current] : [current, other])
    }))
    render(<AlertRulesPanel onError={onError} />)

    fireEvent.click(await screen.findByLabelText(/^High score、/))
    fireEvent.change(screen.getByRole('textbox', { name: 'ルール名' }), { target: { value: 'Other' } })
    fireEvent.click(screen.getByRole('button', { name: '追加' }))
    await waitFor(() => expect(reads).toBe(2))

    fireEvent.change(screen.getByLabelText('High score のルール名'), { target: { value: 'Renamed' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(onError).toHaveBeenLastCalledWith(expect.stringMatching(/リクエストに失敗/)))
    await act(async () => finishOldRead(jsonResponse([rule, other])))

    expect(screen.getByLabelText('Renamed のルール名')).toHaveValue('Renamed')
    expect(screen.getByLabelText(/^Other、/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Renamed の閾値'), { target: { value: '90' } })
    const renamedRow = screen.getByLabelText(/^Renamed、/).closest('li')!
    fireEvent.click(within(renamedRow).getByRole('button', { name: '保存' }))
    await waitFor(() => expect(patches).toEqual([
      { revision: initialRevision, name: 'Renamed' },
      { revision: recentRevision, config: { threshold: 90, cooldown_minutes: 30 } },
    ]))
    expect(screen.queryByRole('button', { name: '編集を破棄して読み直す' })).not.toBeInTheDocument()
  })
})

it('障害パターンを複数選択して作り、一覧の行でパターンと再通知間隔を編集する', async () => {
  const revision = '81d535f3-9d2b-4050-a276-284566833a48'
  let rules: Record<string, unknown>[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/metrics/catalog') return jsonResponse({ metrics: [] })
    if (url === '/api/event-patterns') {
      return jsonResponse([
        { id: 'apd-timeout', title: 'APD のタイムアウト' },
        { id: 'ha-failover', title: 'HA によるフェイルオーバー' },
      ].map((pattern) => ({
        ...pattern, description: '', level: 'error', kind: 'sequence',
        steps: [{ event_types: ['E'] }], within_minutes: 30, min_count: null,
      })))
    }
    if (init?.method === 'POST') {
      rules = [{
        ...JSON.parse(String(init.body)), id: 1, is_enabled: true,
        created_at: '2026-10-01T00:00:00Z', revision,
      }]
      return jsonResponse(rules[0], 201)
    }
    if (init?.method === 'PATCH') {
      rules = [{ ...rules[0], ...JSON.parse(String(init.body)) }]
      return jsonResponse(rules[0])
    }
    return jsonResponse(rules)
  })
  vi.stubGlobal('fetch', fetchMock)
  try {
    render(<AlertRulesPanel onError={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('ルール名'), { target: { value: 'Storage' } })
    fireEvent.change(screen.getByLabelText('タイプ'), { target: { value: 'event_pattern' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: 'APD のタイムアウト' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'HA によるフェイルオーバー' }))
    fireEvent.change(screen.getByLabelText('再通知間隔（分）', { exact: true }), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: '追加' }))
    const row = await screen.findByLabelText('Storage、警告、障害パターン、有効')
    expect(rules[0].config).toEqual({ pattern_ids: ['apd-timeout', 'ha-failover'], cooldown_minutes: 12 })
    fireEvent.click(row)
    const edit = within(row.closest('li')!)
    const patterns = within(edit.getByRole('group', { name: 'Storage の対象のパターン' }))
    fireEvent.click(patterns.getByRole('checkbox', { name: 'HA によるフェイルオーバー' }))
    fireEvent.change(edit.getByLabelText(/Storage の再通知間隔/), { target: { value: '20' } })
    fireEvent.click(edit.getByRole('button', { name: '保存' }))
    await waitFor(() => {
      expect(rules[0].config).toEqual({ pattern_ids: ['apd-timeout'], cooldown_minutes: 20 })
    })
  } finally {
    vi.unstubAllGlobals()
  }
})
