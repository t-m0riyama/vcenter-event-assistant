/**
 * @vitest-environment happy-dom
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { AUTH_DISABLED_ME, AuthContext } from './auth/authContext'
import type { Role } from './api/schemas'
import { INCIDENT_DETAIL, INCIDENT_ID, INCIDENT_LIST, INCIDENT_TITLE, SNAPSHOT_ID } from './test/incidentFixtures'
import { emptyViewResponse, jsonResponse, VIEW_RESPONSE_EXAMPLE } from './test/timelineViewFixtures'

const listHash = '#/incidents'
const detailHash = `${listHash}/${INCIDENT_ID}`
const detailPath = `/api/incidents/${INCIDENT_ID}`
const snapshotPath = `/api/incident-timeline/snapshots/manual/${SNAPSHOT_ID}`
const tab = (name: string) => within(document.querySelector('nav.tabs') as HTMLElement).getByRole('button', { name })
const respond404 = () => jsonResponse({ detail: 'missing' }, 404)

function renderApp(role: Role = 'admin', authEnabled = true, displayName = '運用者') {
  const roles: Role[] = ['viewer', 'operator', 'admin']
  return render(
    <AuthContext.Provider value={{
      me: { ...AUTH_DISABLED_ME, auth_enabled: authEnabled, display_name: displayName, username: 'op', role },
      hasRole: (minimum) => roles.indexOf(role) >= roles.indexOf(minimum),
      logout: vi.fn(),
      refresh: vi.fn(),
    }}>
      <App />
    </AuthContext.Provider>,
  )
}

describe('App のインシデント画面', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let snapshotMissing: boolean
  let snapshotUnreadable: boolean
  let updateCode: string
  let snapshotHasResult: boolean
  let latest = INCIDENT_DETAIL
  let updateStatus: number
  let detailStatus: number

  beforeEach(() => {
    snapshotMissing = false
    snapshotUnreadable = false
    snapshotHasResult = true
    latest = INCIDENT_DETAIL
    updateStatus = 409
    detailStatus = 200
    updateCode = 'incident_stale'
    window.history.replaceState(null, '', detailHash)
    fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), location.href)
      if (url.pathname === '/api/incidents' && init?.method === 'POST') return jsonResponse({
        incident: INCIDENT_DETAIL, link_results: { events: [], alerts: [], snapshots: [] },
      }, 201)
      if (url.pathname === '/api/incidents') return jsonResponse(INCIDENT_LIST)
      if (url.pathname === detailPath && init?.method === 'PATCH') {
        if (updateStatus === 200) return jsonResponse({ ...latest, ...JSON.parse(String(init.body)) })
        return jsonResponse({ detail: 'ユーザーが切り替わりました' }, updateStatus, { 'X-VEA-Error-Code': updateCode })
      }
      if (url.pathname === detailPath && init?.method !== 'DELETE') return jsonResponse(latest, detailStatus)
      if (url.pathname === '/api/config') return jsonResponse({
        event_retention_days: 7, metric_retention_days: 7, perf_sample_interval_seconds: 300,
      })
      if (url.pathname === '/api/vcenters') return jsonResponse([])
      if (url.pathname === '/api/incident-timeline/view') return jsonResponse(emptyViewResponse())
      if (url.pathname === snapshotPath) {
        const { from_time: from, to_time: to, operator_note, created_at } = INCIDENT_DETAIL.snapshots[0]
        return snapshotMissing ? respond404() : jsonResponse({
          snapshot_id: SNAPSHOT_ID, from, to, operator_note, created_at, timestamp_utc: created_at, has_result: snapshotHasResult,
          view_request: { from, to }, build_request_payload: { from, to },
          result: !snapshotHasResult ? null : snapshotUnreadable ? { legacy: true } : VIEW_RESPONSE_EXAMPLE,
        })
      }
      return respond404()
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('一覧の検索と絞り込み、詳細への履歴追加と戻る、タブ切り替えでの書き戻し', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    expect(tab('タイムライン').nextElementSibling).toBe(tab('インシデント'))
    expect(tab('インシデント').querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    const item = await screen.findByRole('link', { name: INCIDENT_TITLE })
    expect(screen.getByRole('combobox', { name: '状態' })).toHaveValue('unresolved')
    expect(screen.getByRole('columnheader', { name: '紐付け' })).toBeVisible()
    const initialHistory = window.history.length
    fireEvent.click(item)
    expect(window.history.length).toBe(initialHistory + 1)
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    fireEvent.click(tab('タイムライン'))
    await waitFor(() => expect(location.hash).toMatch(/^#\/timeline/))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    act(() => window.history.back())
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    fireEvent.change(screen.getByRole('combobox', { name: '状態' }), { target: { value: 'resolved' } })
    fireEvent.change(screen.getByRole('searchbox', { name: '件名' }), { target: { value: '切断' } })
    fireEvent.click(screen.getByRole('button', { name: '検索' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => {
      const params = new URL(String(url), location.href).searchParams
      return params.get('status') === 'resolved' && params.get('q') === '切断'
    })).toBe(true))
  })

  it('hashchange で別の詳細を開き、404 なら一覧に戻す', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    act(() => { location.hash = '#/incidents/no-such-incident' })
    expect(await screen.findByRole('alert', { name: '' })).toHaveTextContent('インシデントが見つかりません')
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it.each(['viewer', 'operator', 'admin'] as const)('%s の権限で操作を表示する', async (role) => {
    renderApp(role)
    expect(await screen.findByText('管理ネットワークを調査中')).toBeVisible()
    expect(screen.getByText('再発の有無を確認')).toBeVisible()
    expect(screen.getByText('（管理者が削除しました）')).toBeVisible()
    expect(screen.getByRole('link', { name: '前後 30 分のタイムライン' })).toHaveAttribute('href', expect.stringContaining('entity_moid=host-1'))
    expect(screen.getByText('元の行は削除されています')).toBeVisible()
    expect(screen.getByRole('button', { name: 'タイムラインで開く' })).toBeVisible()
    expect(screen.queryAllByRole('button', { name: '外す' })).toHaveLength(role === 'viewer' ? 0 : 3)
    expect(screen.queryAllByRole('button', { name: '編集' })).toHaveLength(role === 'viewer' ? 0 : 1)
    expect(screen.queryAllByRole('button', { name: 'メモを追加' })).toHaveLength(role === 'viewer' ? 0 : 1)
    expect(screen.queryAllByRole('button', { name: /^削除$|^インシデントを削除$/ })).toHaveLength(role === 'admin' ? 2 : 0)
    fireEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    await screen.findByRole('link', { name: INCIDENT_TITLE })
    expect(screen.queryAllByRole('button', { name: 'インシデントを作る' })).toHaveLength(role === 'viewer' ? 0 : 1)
  })

  it('自分を担当に指定し、incident_stale なら読み直しを案内する', async () => {
    renderApp('operator')
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByRole('button', { name: '自分' }))
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue('運用者（op）')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('ほかの人が更新しました。読み直してください')).toBeVisible()
    const [, patch] = fetchMock.mock.calls.find(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')!
    expect(JSON.parse(patch.body)).toEqual({ assignee: '運用者（op）', revision: INCIDENT_DETAIL.revision })
    latest = {
      ...INCIDENT_DETAIL,
      revision: '44444444-4444-4444-8444-444444444444',
      assignee: '別の担当者',
      summary: 'ほかの人が要約を変更しました',
    }
    fireEvent.click(screen.getByRole('button', { name: '読み直す' }))
    expect(await screen.findByText('読み直した最新の内容')).toBeVisible()
    expect(screen.getByText('別の担当者')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue('運用者（op）')
    expect(screen.getByRole('textbox', { name: '要約' })).toHaveValue(latest.summary)
    updateStatus = 200
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('button', { name: '編集' })).toBeVisible()
    const patches = fetchMock.mock.calls.filter(([url, options]) => String(url).endsWith(detailPath) && options?.method === 'PATCH')
    expect(JSON.parse(patches[1][1].body)).toEqual({ assignee: '運用者（op）', revision: latest.revision })
  })

  it('別の 409 は競合として扱わず、認証が無効なら「自分」を表示しない', async () => {
    updateCode = 'principal_changed'
    renderApp('admin', false)
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    expect(screen.queryByRole('button', { name: '自分' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByText('ユーザーが切り替わりました')).toBeVisible()
    expect(screen.queryByRole('button', { name: '読み直す' })).toBeNull()
  })

  it('同じスナップショットを続けて開け、結果はハッシュの条件と分けて扱う', async () => {
    renderApp()
    for (let count = 1; count <= 2; count++) {
      fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
      expect(await screen.findByRole('button', { name: /VmPoweredOffEvent/ })).toBeVisible()
      expect(tab('タイムライン')).toHaveClass('active')
      expect(location.hash).toMatch(/^#\/timeline\?from=/)
      expect(location.hash).not.toContain(SNAPSHOT_ID)
      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(snapshotPath))).toHaveLength(count)
      fireEvent.click(tab('インシデント'))
    }
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
  })

  it('スナップショットの 404 はタイムラインのエラー欄に表示する', async () => {
    snapshotMissing = true
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
    expect(await screen.findByText('スナップショットを開けませんでした')).toHaveClass('panel-error-banner')
    expect(tab('タイムライン')).toHaveClass('active')
  })

  it('保存結果が読めなければ保存した条件で再集計し、遅れて届く書き戻しでも条件と注記を保つ', async () => {
    snapshotUnreadable = true
    const rollingHash = '#/timeline?range=1h'
    let delayed: HashChangeEvent | undefined
    let delivered = false
    // 通常の通知は止め、React が固定期間を反映して URL を書き戻す直前に通知を届ける。
    const holdRollingHash = (event: HashChangeEvent) => {
      if (!delivered && event.newURL === delayed?.newURL) event.stopImmediatePropagation()
    }
    window.addEventListener('hashchange', holdRollingHash, true)
    const replaceState = window.history.replaceState.bind(window.history)
    const replace = vi.spyOn(window.history, 'replaceState').mockImplementation((data, unused, url) => {
      const oldURL = window.location.href
      const hash = new URL(url ?? oldURL, oldURL).hash
      if (hash.startsWith('#/timeline?from=') && delayed && !delivered) {
        delivered = true
        window.dispatchEvent(delayed)
      }
      replaceState(data, unused, url)
      if (hash === rollingHash && oldURL !== window.location.href) {
        delayed = new HashChangeEvent('hashchange', { oldURL, newURL: window.location.href })
      }
    })
    try {
      renderApp()
      fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
      const notice = /保存時点の結果はいまの形式で読めない/
      expect(await screen.findByText(notice)).toBeVisible()
      await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
        String(url).endsWith('/api/incident-timeline/view') && JSON.parse(init.body).from === '2026-03-22T00:00:00.000Z')).toBe(true))
      await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 0)) })
      expect(delivered).toBe(true)
      expect(screen.getByText(notice)).toBeVisible()
      expect(location.hash).toMatch(/^#\/timeline\?from=/)
      expect(new URLSearchParams(location.hash.split('?')[1]).get('from')).toBe('2026-03-22T00:00:00.000Z')
    } finally {
      replace.mockRestore()
      window.removeEventListener('hashchange', holdRollingHash, true)
    }
  })

  it('タイムラインへ移っても編集中の項目、メモ、進行中の出力を保つ', async () => {
    let finishExport: (response: Response) => void = () => {}
    let exportSignal: AbortSignal | null | undefined
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes(`${snapshotPath}/export?`)) {
        exportSignal = init?.signal
        return new Promise<Response>((resolve) => { finishExport = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '書きかけのメモ' } })
    fireEvent.click(screen.getByRole('button', { name: /調査資料を Markdown で出力/ }))
    await waitFor(() => expect(exportSignal).toBeDefined())
    fireEvent.click(screen.getByRole('button', { name: 'タイムラインで開く' }))
    expect(await screen.findByRole('button', { name: /VmPoweredOffEvent/ })).toBeVisible()
    expect(screen.queryByRole('textbox', { name: 'メモ' })).toBeNull()
    expect(exportSignal?.aborted).toBe(false)
    fireEvent.click(tab('インシデント'))
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('書きかけのメモ')
    expect(screen.getByRole('button', { name: /調査資料を Markdown で出力/ })).toHaveTextContent('出力中…')
    await act(async () => { finishExport(respond404()) })
    expect(await screen.findByText(/スナップショットが見つかりません/)).toBeVisible()
    // タブに戻ると詳細を 1 回だけ読み直し、読み直したあとも下書きを保つ
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(detailPath))).toHaveLength(2))
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('書きかけのメモ')
  })

  it('ほかのタブから戻ると紐付けを読み直し、編集の下書きがあれば項目と revision は元のまま保つ', async () => {
    updateStatus = 200
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    const newRevision = '44444444-4444-4444-8444-444444444444'
    latest = {
      ...INCIDENT_DETAIL,
      title: 'ほかの人が変えた件名',
      revision: newRevision,
      events: [...INCIDENT_DETAIL.events, { ...INCIDENT_DETAIL.events[0], id: 2, event_id: 124, vmware_key: 1235, event_type: 'DatastoreRemovedOnHostEvent' }],
    }
    fireEvent.click(tab('イベント'))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByText('DatastoreRemovedOnHostEvent')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const [, patchInit] = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    // 読み直す前の revision で送るので、ほかの人の変更とぶつかれば 409 になる
    expect(JSON.parse(String(patchInit?.body))).toMatchObject({ revision: INCIDENT_DETAIL.revision, title: '編集中の件名' })
  })

  it('メモを追加したあとの読み直しでも、編集の下書きがあれば revision を元のまま保つ', async () => {
    updateStatus = 200
    const newEntry = { ...INCIDENT_DETAIL.entries[0], id: 3, body: '追加したメモ' }
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') return Promise.resolve(jsonResponse(newEntry, 201))
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '編集中の件名' } })
    latest = {
      ...INCIDENT_DETAIL,
      title: 'ほかの人が変えた件名',
      revision: '44444444-4444-4444-8444-444444444444',
      entries: [...INCIDENT_DETAIL.entries, newEntry],
    }
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '追加したメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith(detailPath) && !init?.method)).toHaveLength(2))
    expect(await screen.findByText('追加したメモ')).toBeVisible()
    expect(screen.getByRole('textbox', { name: '件名' })).toHaveValue('編集中の件名')
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const [, patchInit] = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')!
    expect(JSON.parse(String(patchInit?.body))).toMatchObject({ revision: INCIDENT_DETAIL.revision, title: '編集中の件名' })
  })

  it('タブに戻ったときの読み直しが書き込みより遅れて届いても、書き込みの結果を古い内容で上書きしない', async () => {
    const newEntry = { ...INCIDENT_DETAIL.entries[0], id: 3, body: '追加したメモ' }
    let deferNext = false
    let finishStale: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') return Promise.resolve(jsonResponse(newEntry, 201))
      if (String(input).endsWith(detailPath) && !init?.method && deferNext) {
        deferNext = false
        return new Promise<Response>((resolve) => { finishStale = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    fireEvent.click(tab('イベント'))
    deferNext = true
    fireEvent.click(tab('インシデント'))
    await waitFor(() => expect(deferNext).toBe(false))
    latest = { ...INCIDENT_DETAIL, entries: [...INCIDENT_DETAIL.entries, newEntry] }
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '追加したメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    expect(await screen.findByText('追加したメモ')).toBeVisible()
    // 書き込みの前に始めた読み直しの応答（メモが無い古い内容）を、あとから届ける
    await act(async () => { finishStale(jsonResponse(INCIDENT_DETAIL)) })
    expect(screen.getByText('追加したメモ')).toBeVisible()
  })

  it('下書きが無ければ、ほかのタブから戻ったときに詳細をすべて最新にする', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    latest = { ...INCIDENT_DETAIL, title: 'ほかの人が変えた件名', revision: '44444444-4444-4444-8444-444444444444' }
    fireEvent.click(tab('イベント'))
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: 'ほかの人が変えた件名' })).toBeVisible()
  })

  it.each(['一覧に戻る', 'インシデント'] as const)('%s で一覧への履歴を追加する', async (operation) => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    await screen.findByRole('heading', { name: INCIDENT_TITLE })
    const length = window.history.length
    fireEvent.click(operation === 'インシデント' ? tab(operation) : screen.getByRole('button', { name: operation }))
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    expect(window.history.length).toBe(length + 1)
    act(() => window.history.back())
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
  })

  it('一覧で作成した詳細からブラウザの「戻る」で一覧を開ける', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    await screen.findByRole('link', { name: INCIDENT_TITLE })
    fireEvent.click(screen.getByRole('button', { name: 'インシデントを作る' }))
    const form = within(screen.getByRole('dialog', { name: 'インシデントを作る' }))
    fireEvent.change(form.getByRole('textbox', { name: '件名' }), { target: { value: INCIDENT_TITLE } })
    fireEvent.click(form.getByRole('button', { name: '作成' }))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    act(() => window.history.back())
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it('404 の表示は絞り込みとタブ移動でそれぞれ消える', async () => {
    window.history.replaceState(null, '', '#/incidents/missing')
    renderApp()
    const message = 'インシデントが見つかりません'
    expect(await screen.findByText(message)).toBeVisible()
    fireEvent.change(screen.getByRole('combobox', { name: '状態' }), { target: { value: 'all' } })
    expect(screen.queryByText(message)).toBeNull()
    act(() => { location.hash = '#/incidents/missing-again' })
    expect(await screen.findByText(message)).toBeVisible()
    fireEvent.click(tab('タイムライン'))
    fireEvent.click(tab('インシデント'))
    expect(screen.queryByText(message)).toBeNull()
  })

  it('タブが切り替わると選択したタブをアニメーションなしで表示範囲に入れる', async () => {
    const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
    try {
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      fireEvent.click(tab('タイムライン'))
      fireEvent.click(tab('インシデント'))
      expect(scroll.mock.instances.at(-1)).toBe(tab('インシデント'))
      expect(scroll).toHaveBeenLastCalledWith({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
    } finally {
      scroll.mockRestore()
    }
  })

  it('長い表示名を短くしても「自分」のユーザー名を残す', async () => {
    renderApp('operator', true, '名'.repeat(256))
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.click(screen.getByRole('button', { name: '自分' }))
    expect(screen.getByRole('textbox', { name: '担当' })).toHaveValue(`${'名'.repeat(252)}（op）`)
  })

  it('メモを保存できたら再読込に失敗しても下書きを消す', async () => {
    const originalFetch = fetchMock.getMockImplementation()!
    const body = '一度だけ追加するメモ'
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') {
        detailStatus = 503
        return Promise.resolve(jsonResponse({ ...INCIDENT_DETAIL.entries[0], id: 3, body }, 201))
      }
      return originalFetch(input, init)
    })
    renderApp()
    const note = await screen.findByRole('textbox', { name: 'メモ' })
    fireEvent.change(note, { target: { value: body } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    expect(await screen.findByText('メモを追加しました。最新の経過を読み込めませんでした。')).toBeVisible()
    expect(screen.getByText(body)).toBeVisible()
    expect(note).toHaveValue('')
    expect(screen.getByRole('button', { name: 'メモを追加' })).toBeDisabled()
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith('/entries') && init?.method === 'POST')).toHaveLength(1)
  })

  it.each(['保存', 'メモを追加', 'インシデントを削除'] as const)('%s で 404 なら一覧に戻る', async (action) => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    try {
      updateStatus = 404
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      if (action === '保存') fireEvent.click(screen.getByRole('button', { name: '編集' }))
      if (action === 'メモを追加') fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: 'メモの下書き' } })
      fireEvent.click(screen.getAllByRole('button', { name: action })[0])
      expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()
      expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(listHash)
    } finally {
      confirm.mockRestore()
    }
  })

  it.each([
    ['外す', 'events', 'Incident link not found', 'すでに外されていました', false],
    ['削除', 'entries', 'Incident entry not found', 'すでに削除されていました', false],
    ['外す', 'events', 'Incident not found', 'インシデントが見つかりません', true],
  ] as const)('%s が 404 のとき、再取得の結果で %s の表示を決める', async (action, kind, serverMessage, message, missing) => {
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes(`${detailPath}/${kind}/`) && init?.method === 'DELETE') {
        latest = { ...latest, [kind]: [] }
        detailStatus = missing ? 404 : 200
        return Promise.resolve(jsonResponse({ detail: serverMessage }, 404))
      }
      return originalFetch(input, init)
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    try {
      renderApp()
      fireEvent.click((await screen.findAllByRole('button', { name: action }))[0])
      expect(await screen.findByText(message)).toBeVisible()
      if (missing) {
        expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
        expect(location.hash).toBe(listHash)
      } else {
        expect(screen.getByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
        expect(screen.queryByText(kind === 'events' ? '接続を失いました' : INCIDENT_DETAIL.entries[0].body)).toBeNull()
        expect(location.hash).toBe(detailHash)
      }
      expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith(detailPath))).toHaveLength(2)
    } finally {
      confirm.mockRestore()
    }
  })

  it('タイムラインからタブで詳細に戻るときは履歴を増やさず、一覧への遷移だけ履歴に積む', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    const openTimeline = await screen.findByRole('button', { name: 'タイムラインで開く' })
    const length = window.history.length
    fireEvent.click(openTimeline)
    await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    expect(window.history.length).toBe(length + 1)
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(detailHash)
    expect(window.history.length).toBe(length + 1)
    fireEvent.click(screen.getByRole('button', { name: '一覧に戻る' }))
    expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
    expect(location.hash).toBe(listHash)
    expect(window.history.length).toBe(length + 2)
  })

  it.each(['タイムラインで開く', '前後 30 分のタイムライン'] as const)('%s の後にブラウザで戻ると同じ詳細と下書きに戻る', async (action) => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('link', { name: INCIDENT_TITLE }))
    fireEvent.click(await screen.findByRole('button', { name: '編集' }))
    fireEvent.change(screen.getByRole('textbox', { name: '件名' }), { target: { value: '下書きの件名' } })
    fireEvent.change(screen.getByRole('textbox', { name: 'メモ' }), { target: { value: '下書きのメモ' } })
    if (action === 'タイムラインで開く') {
      fireEvent.click(screen.getByRole('button', { name: action }))
      await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    } else {
      const link = screen.getByRole<HTMLAnchorElement>('link', { name: action })
      act(() => { link.click() })
    }
    await waitFor(() => expect(tab('タイムライン')).toHaveClass('active'))
    act(() => window.history.back())
    expect(await screen.findByRole('textbox', { name: '件名' })).toHaveValue('下書きの件名')
    expect(screen.getByRole('textbox', { name: 'メモ' })).toHaveValue('下書きのメモ')
    expect(location.hash).toBe(detailHash)
  })

  it.each(['編集', 'メモ'] as const)('%s の下書きがあればタブの押し直しで破棄を確認する', async (draft) => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    try {
      renderApp()
      await screen.findByRole('heading', { name: INCIDENT_TITLE })
      if (draft === '編集') fireEvent.click(screen.getByRole('button', { name: '編集' }))
      const field = screen.getByRole('textbox', { name: draft === '編集' ? '件名' : 'メモ' })
      fireEvent.change(field, { target: { value: '未保存の入力' } })
      fireEvent.click(tab('インシデント'))
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('保存していない入力'))
      expect(field).toHaveValue('未保存の入力')
      expect(location.hash).toBe(detailHash)
      fireEvent.click(tab('インシデント'))
      expect(await screen.findByRole('link', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(listHash)
    } finally {
      confirm.mockRestore()
    }
  })

  it('詳細の一時的な読み込みエラーから再試行できる', async () => {
    detailStatus = 503
    renderApp()
    const retry = await screen.findByRole('button', { name: '読み直す' })
    detailStatus = 200
    fireEvent.click(retry)
    expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
    expect(screen.queryByRole('button', { name: '読み直す' })).toBeNull()
  })

  it('未送信の作成ダイアログはタブ移動で閉じる', async () => {
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'インシデントを作る' }))
    fireEvent.click(tab('タイムライン'))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(tab('インシデント'))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it.each(['成功', '失敗'] as const)('タブを離れている間の作成が%sしたら、一覧に戻ったときに結果を表示する', async (outcome) => {
    let finishCreate: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/incidents') && init?.method === 'POST') {
        return new Promise<Response>((resolve) => { finishCreate = resolve })
      }
      return originalFetch(input, init)
    })
    window.history.replaceState(null, '', listHash)
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'インシデントを作る' }))
    const form = within(screen.getByRole('dialog'))
    fireEvent.change(form.getByRole('textbox', { name: '件名' }), { target: { value: INCIDENT_TITLE } })
    fireEvent.click(form.getByRole('button', { name: '作成' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith('/api/incidents') && init?.method === 'POST')).toBe(true))
    expect(form.getByRole('button', { name: '作成' })).toBeDisabled()
    fireEvent.click(tab('タイムライン'))
    expect(screen.queryByRole('dialog')).toBeNull()
    const error = 'インシデントを作成できませんでした'
    const response = outcome === '成功'
      ? jsonResponse({ incident: INCIDENT_DETAIL, link_results: { events: [], alerts: [], snapshots: [] } }, 201)
      : jsonResponse({ detail: error }, 409)
    await act(async () => { finishCreate(response) })
    expect(tab('タイムライン')).toHaveClass('active')
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(tab('インシデント'))
    const result = within(await screen.findByRole('dialog', { name: 'インシデントを作る' }))
    expect(location.hash).toBe(listHash)
    if (outcome === '成功') {
      expect(result.getByRole('status')).toHaveTextContent('インシデントを作成しました')
      const link = result.getByRole<HTMLAnchorElement>('link', { name: 'インシデントを開く' })
      expect(link).toHaveAttribute('href', detailHash)
      act(() => { link.click() })
      expect(await screen.findByRole('heading', { name: INCIDENT_TITLE })).toBeVisible()
      expect(location.hash).toBe(detailHash)
    } else {
      expect(result.getByRole('alert')).toHaveTextContent(error)
      expect(result.getByRole('textbox', { name: '件名' })).toHaveValue(INCIDENT_TITLE)
      expect(result.getByRole('button', { name: '作成' })).toBeEnabled()
    }
  })

  it('別タブにいる間に書き込みが 404 になったら、インシデントに戻ったときに知らせる', async () => {
    let finishNote: (response: Response) => void = () => {}
    const originalFetch = fetchMock.getMockImplementation()!
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`${detailPath}/entries`) && init?.method === 'POST') {
        return new Promise<Response>((resolve) => { finishNote = resolve })
      }
      return originalFetch(input, init)
    })
    renderApp()
    fireEvent.change(await screen.findByRole('textbox', { name: 'メモ' }), { target: { value: '送信中のメモ' } })
    fireEvent.click(screen.getByRole('button', { name: 'メモを追加' }))
    fireEvent.click(screen.getByRole('button', { name: 'タイムラインで開く' }))
    await screen.findByRole('button', { name: /VmPoweredOffEvent/ })
    await act(async () => { finishNote(respond404()) })
    expect(location.hash).toMatch(/^#\/timeline/)
    expect(screen.queryByText('インシデントが見つかりません')).toBeNull()
    fireEvent.click(tab('インシデント'))
    expect(await screen.findByText('インシデントが見つかりません')).toBeVisible()
    expect(location.hash).toBe(listHash)
  })

  it('結果の無いスナップショットは保存条件で再集計し、読込失敗の注記を表示しない', async () => {
    snapshotHasResult = false
    renderApp()
    fireEvent.click(await screen.findByRole('button', { name: 'タイムラインで開く' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) =>
      String(url).endsWith('/api/incident-timeline/view') && JSON.parse(init.body).from === '2026-03-22T00:00:00.000Z')).toBe(true))
    expect(screen.queryByText(/保存時点の結果はいまの形式で読めない/)).toBeNull()
  })

})
