/** `tests/test_incident_timeline_view_api.py` が確かめている応答の形に合わせた例。 */
export const VIEW_RESPONSE_EXAMPLE = {
  from_utc: '2026-03-22T00:00:00Z',
  to_utc: '2026-03-22T01:00:00Z',
  anchor_utc: null,
  bucket_seconds: 60,
  overview: [
    {
      bucket_start_utc: '2026-03-22T00:00:00Z',
      event_total: 3,
      event_notable: 1,
      alert: 1,
      metric_breach: 0,
      log_error: 0,
    },
  ],
  items: [
    {
      id: 'event:12',
      kind: 'event',
      timestamp_utc: '2026-03-22T00:10:00',
      end_utc: '2026-03-22T00:12:00',
      level: 'warning',
      title: 'VmPoweredOffEvent',
      detail: 'vm-a was powered off',
      entity_name: 'vm-a',
      entity_type: 'HostSystem',
      vcenter_id: '11111111-1111-1111-1111-111111111111',
      vcenter_name: 'vc-detail',
      score: 55,
      count: 2,
      ref: { event_id: 12, event_type: 'VmPoweredOffEvent' },
    },
    {
      id: 'alert:4',
      kind: 'alert',
      timestamp_utc: '2026-03-22T00:20:00+00:00',
      level: 'critical',
      title: 'CPU 高負荷: 発火',
      count: 1,
      ref: { alert_history_id: 4, alert_rule_name: 'CPU 高負荷', alert_state: 'firing' },
    },
  ],
  truncated: false,
  total_items: 2,
  highlights: {
    first_signal: null,
    top_entities: [
      {
        entity_name: 'vm-a',
        entity_type: 'HostSystem',
        vcenter_id: '11111111-1111-1111-1111-111111111111',
        vcenter_name: 'vc-detail',
        item_count: 2,
        first_seen_utc: '2026-03-22T00:10:00Z',
      },
    ],
    new_event_types: [
      { event_type: 'VmPoweredOffEvent', count: 2, first_seen_utc: '2026-03-22T00:10:00Z', max_score: 55 },
    ],
  },
}

/** メトリクスの超過区間の行（契約の追加後の形: ref に構造化した値が入る）。 */
export const METRIC_ITEM_EXAMPLE = {
  id: 'metric:123456',
  kind: 'metric',
  timestamp_utc: '2026-03-22T00:05:00Z',
  end_utc: '2026-03-22T00:15:00Z',
  level: 'warning',
  title: 'CPU 使用率が閾値（80%）を超過',
  detail: 'ピーク 92.5%、サンプル 3 件',
  entity_name: 'esx01',
  entity_type: 'HostSystem',
  vcenter_id: '11111111-1111-4111-8111-111111111111',
  vcenter_name: 'vc-1',
  score: null,
  count: 1,
  ref: {
    metric_key: 'host.cpu.usage_pct',
    entity_moid: 'host-1',
    threshold_pct: 80,
    peak_value: 92.5,
    peak_at_utc: '2026-03-22T00:10:00Z',
    sample_count: 3,
    continues_from_before: false,
    continues_after: false,
  },
}

/** 構造化した値（ref の追加項目）が無い、古いサーバ・追加前のバックエンドの行。 */
export const METRIC_ITEM_LEGACY_EXAMPLE = {
  ...METRIC_ITEM_EXAMPLE,
  id: 'metric:123457',
  ref: { metric_key: 'host.cpu.usage_pct', entity_moid: 'host-1' },
}

/** エラーログの行。同じ出どころの連続が 1 行にまとまり、count に件数が入る。 */
export const LOG_ITEM_EXAMPLE = {
  id: 'log:789',
  kind: 'log',
  timestamp_utc: '2026-03-22T01:00:00Z',
  end_utc: '2026-03-22T01:01:00Z',
  level: 'warning',
  title: 'esx01.example.com vmkernel',
  detail: 'vmhba0: timeout\n  retrying command',
  entity_name: 'esx01.example.com',
  entity_type: 'host',
  vcenter_id: '11111111-1111-4111-8111-111111111111',
  vcenter_name: 'vc-1',
  score: null,
  count: 2,
  ref: { log_id: 789 },
}

export function jsonResponse(data: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** 空の期間に対する応答。 */
export function emptyViewResponse(overrides: Record<string, unknown> = {}) {
  return {
    from_utc: '2026-03-22T00:00:00Z',
    to_utc: '2026-03-22T01:00:00Z',
    anchor_utc: null,
    bucket_seconds: 60,
    overview: [],
    items: [],
    truncated: false,
    total_items: 0,
    highlights: { first_signal: null, top_entities: [], new_event_types: [] },
    ...overrides,
  }
}

type ViewCall = { body: Record<string, unknown>; resolve: (res: Response) => void }

/**
 * `fetch` のモック。`/api/vcenters` と手動スナップショット一覧は空で返し、view への要求は
 * `calls` に溜めて、テストが好きな順で `resolve` する。
 */
export function installTimelineFetchMock(options: { vcenters?: unknown[]; snapshots?: unknown[] } = {}) {
  const calls: ViewCall[] = []
  const extra = new Map<string, (url: string, init?: RequestInit) => Response>()
  const mock = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input)
    if (url.endsWith('/api/vcenters')) return Promise.resolve(jsonResponse(options.vcenters ?? []))
    if (url.includes('/api/incident-timeline/snapshots/manual?')) {
      const items = options.snapshots ?? []
      return Promise.resolve(jsonResponse({ items, total: items.length, limit: 20, offset: 0 }))
    }
    if (url.endsWith('/api/incident-timeline/view')) {
      return new Promise((resolve) => {
        calls.push({ body: JSON.parse(String(init?.body)) as Record<string, unknown>, resolve })
      })
    }
    for (const [prefix, handler] of extra) {
      if (url.startsWith(prefix)) return Promise.resolve(handler(url, init))
    }
    return Promise.resolve(new Response('not found', { status: 404 }))
  }
  return { fetchMock: mock, calls, extra }
}
