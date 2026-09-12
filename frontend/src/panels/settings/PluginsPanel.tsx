import { Fragment, useCallback, useEffect, useRef, useState } from 'react'

import { apiDelete, apiGet, apiPatch, apiPost, apiPostForm } from '../../api'
import {
  collectorReloadSchema,
  collectorStatusListSchema,
  installedPluginListSchema,
  type CollectorRunStatus,
  type CollectorStatus,
  type CollectorStatusList,
  type InstalledPluginList,
} from '../../api/schemas'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'
import { toErrorMessage } from '../../utils/errors'
import './PluginsPanel.css'

const COLLECTOR_STATUS_LABELS: Record<string, string> = {
  enabled: '有効',
  disabled: '無効',
  failed: 'エラー',
}

const RUN_STATUS_LABELS: Record<string, string> = {
  idle: '未実行',
  running: '実行中',
  ok: '成功',
  failed: '失敗',
}

const INSTALL_STATUS_LABELS: Record<string, string> = {
  installing: 'インストール中',
  installed: 'インストール済み',
  failed: '失敗',
}

const ENV_LOCK_HINT = '環境変数で固定されているため、画面からは変更できません。'
/** インストールは数十秒かかりうるため、完了までポーリングする。 */
const INSTALL_POLL_INTERVAL_MS = 2000

function collectorStatusClass(status: string): string {
  if (status === 'enabled') return 'plugin-status-badge--enabled'
  if (status === 'failed') return 'badge--error'
  return ''
}

function runStatusClass(status: string): string {
  if (status === 'ok') return 'plugin-status-badge--enabled'
  if (status === 'running') return 'badge--info'
  if (status === 'failed') return 'badge--error'
  return ''
}

function installStatusClass(status: string): string {
  if (status === 'installed') return 'plugin-status-badge--enabled'
  if (status === 'installing') return 'badge--info'
  return 'badge--error'
}

function dataKindsLabel(dataKinds: readonly string[]): string {
  if (dataKinds.length === 0) return '—'
  return dataKinds
    .map((kind) => {
      if (kind === 'event') return 'イベント'
      if (kind === 'metric') return 'メトリクス'
      return kind
    })
    .join(' / ')
}

function sourceLabel(source: string): string {
  if (source === 'builtin') return '組み込み'
  if (source.startsWith('entry_point:')) return '外部'
  if (source === 'configuration') return '設定のみ'
  if (source === 'discovery') return '検出'
  return source
}

function secondsLabel(value: number | null): string {
  return value === null ? '—' : `${value} 秒`
}

function RunDate({ value, timeZone }: { readonly value: string | null; readonly timeZone: string }) {
  return value ? formatIsoInTimeZone(value, timeZone) : '—'
}

function RunsTable({ runs, timeZone }: { readonly runs: CollectorRunStatus[]; readonly timeZone: string }) {
  if (runs.length === 0) {
    return <p className="no-data plugin-runs-empty">実行記録はありません。</p>
  }

  return (
    <div className="plugin-table-container">
      <table className="table plugin-runs-table">
        <thead>
          <tr>
            <th>vCenter</th>
            <th>状態</th>
            <th>使用バージョン</th>
            <th>開始日時</th>
            <th>成功日時</th>
            <th>失敗日時</th>
            <th>直近成功時の追加件数</th>
            <th>エラー</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.vcenter_id}>
              <td>
                <span className="plugin-vcenter-name">{run.vcenter_name}</span>
                <span className="plugin-metadata">{run.vcenter_id}</span>
              </td>
              <td>
                <span className={`badge ${runStatusClass(run.status)}`}>
                  {RUN_STATUS_LABELS[run.status] ?? run.status}
                </span>
              </td>
              <td>{run.collector_version || '—'}</td>
              <td><RunDate value={run.last_started_at} timeZone={timeZone} /></td>
              <td><RunDate value={run.last_success_at} timeZone={timeZone} /></td>
              <td><RunDate value={run.last_failure_at} timeZone={timeZone} /></td>
              <td>
                イベント {run.events_inserted} / メトリクス {run.metrics_inserted}
              </td>
              <td className="plugin-error-cell">{run.error || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 有効/無効・実行間隔・タイムアウトの編集フォーム。保存は DB のみで、反映はリロード時。 */
function CollectorSettingsForm({
  collector,
  disabled,
  onSave,
}: {
  readonly collector: CollectorStatus
  readonly disabled: boolean
  readonly onSave: (
    values: { enabled?: boolean; interval_seconds?: number; timeout_seconds?: number },
  ) => Promise<void>
}) {
  const [interval, setInterval] = useState(String(collector.interval_seconds ?? ''))
  const [timeout, setTimeout] = useState(String(collector.timeout_seconds ?? ''))

  useEffect(() => {
    setInterval(String(collector.interval_seconds ?? ''))
    setTimeout(String(collector.timeout_seconds ?? ''))
  }, [collector.interval_seconds, collector.timeout_seconds])

  const locked = new Set(collector.env_locked_fields)
  const enabledLocked = locked.has('enabled')
  const intervalLocked = locked.has('interval_seconds')
  const timeoutLocked = locked.has('timeout_seconds')

  return (
    <div className="plugin-settings-form">
      <h3>設定</h3>
      <div className="plugin-settings-row">
        <label>
          <input
            type="checkbox"
            checked={collector.status === 'enabled'}
            disabled={disabled || enabledLocked}
            title={enabledLocked ? ENV_LOCK_HINT : undefined}
            onChange={(event) => void onSave({ enabled: event.target.checked })}
          />
          有効にする
        </label>
        {enabledLocked ? <span className="plugin-env-lock">{ENV_LOCK_HINT}</span> : null}
      </div>

      <div className="plugin-settings-row">
        <label htmlFor={`interval-${collector.id}`}>実行間隔（秒）</label>
        <input
          id={`interval-${collector.id}`}
          type="number"
          min={10}
          max={86400}
          value={interval}
          disabled={disabled || intervalLocked}
          title={intervalLocked ? ENV_LOCK_HINT : undefined}
          onChange={(event) => setInterval(event.target.value)}
        />
        <label htmlFor={`timeout-${collector.id}`}>タイムアウト（秒）</label>
        <input
          id={`timeout-${collector.id}`}
          type="number"
          min={1}
          max={86400}
          value={timeout}
          disabled={disabled || timeoutLocked}
          title={timeoutLocked ? ENV_LOCK_HINT : undefined}
          onChange={(event) => setTimeout(event.target.value)}
        />
        <button
          type="button"
          className="btn"
          disabled={disabled || (intervalLocked && timeoutLocked)}
          onClick={() => {
            const values: { interval_seconds?: number; timeout_seconds?: number } = {}
            if (!intervalLocked && interval !== '') values.interval_seconds = Number(interval)
            if (!timeoutLocked && timeout !== '') values.timeout_seconds = Number(timeout)
            void onSave(values)
          }}
        >
          保存
        </button>
      </div>
      {intervalLocked || timeoutLocked ? (
        <p className="plugin-env-lock">{ENV_LOCK_HINT}</p>
      ) : null}
    </div>
  )
}

/** インストール済み配布物の一覧・追加・削除。 */
function InstalledPluginsSection({
  data,
  busy,
  onUpload,
  onInstallRequirement,
  onUninstall,
  timeZone,
}: {
  readonly data: InstalledPluginList | null
  readonly busy: boolean
  readonly onUpload: (file: File) => Promise<void>
  readonly onInstallRequirement: (requirement: string) => Promise<void>
  readonly onUninstall: (distribution: string) => Promise<void>
  readonly timeZone: string
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [requirement, setRequirement] = useState('')

  if (data === null) return null

  return (
    <section className="plugin-install-section">
      <h2>インストール済みプラグイン</h2>

      <div className="plugin-install-controls">
        <label htmlFor="plugin-upload">パッケージ（.whl / .tar.gz）を追加</label>
        <input
          id="plugin-upload"
          ref={fileInputRef}
          type="file"
          accept=".whl,.tar.gz"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (!file) return
            void onUpload(file).finally(() => {
              if (fileInputRef.current) fileInputRef.current.value = ''
            })
          }}
        />
      </div>

      {data.index_install_enabled ? (
        <div className="plugin-install-controls">
          <label htmlFor="plugin-requirement">インデックスから追加</label>
          <input
            id="plugin-requirement"
            type="text"
            placeholder="example-collector==1.0.0"
            value={requirement}
            disabled={busy}
            onChange={(event) => setRequirement(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={busy || requirement.trim() === ''}
            onClick={() => {
              void onInstallRequirement(requirement.trim()).then(() => setRequirement(''))
            }}
          >
            インストール
          </button>
        </div>
      ) : null}

      {data.plugins.length === 0 ? (
        <p className="no-data">動的にインストールされたプラグインはありません。</p>
      ) : (
        <div className="plugin-table-container">
          <table className="table plugin-installed-table">
            <thead>
              <tr>
                <th>配布物</th>
                <th>バージョン</th>
                <th>状態</th>
                <th>取得元</th>
                <th>インストール日時</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.plugins.map((plugin) => (
                <tr key={plugin.distribution}>
                  <td>
                    <span className="plugin-display-name">{plugin.distribution}</span>
                    {plugin.error ? (
                      <span className="plugin-metadata plugin-error-cell">{plugin.error}</span>
                    ) : null}
                  </td>
                  <td>{plugin.version || '—'}</td>
                  <td>
                    <span className={`badge ${installStatusClass(plugin.status)}`}>
                      {INSTALL_STATUS_LABELS[plugin.status] ?? plugin.status}
                    </span>
                  </td>
                  <td>{plugin.origin || '—'}</td>
                  <td>{formatIsoInTimeZone(plugin.installed_at, timeZone)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn--danger"
                      disabled={busy || plugin.status === 'installing'}
                      onClick={() => {
                        if (
                          !window.confirm(
                            `${plugin.distribution} をアンインストールします。よろしいですか？`,
                          )
                        ) {
                          return
                        }
                        void onUninstall(plugin.distribution)
                      }}
                    >
                      削除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** コレクタプラグインの構成・実行状態の表示と、設定変更・リロード・動的インストール。 */
export function PluginsPanel({ onError }: { readonly onError: (message: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [data, setData] = useState<CollectorStatusList | null>(null)
  const [installed, setInstalled] = useState<InstalledPluginList | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const managementEnabled = data?.management_enabled ?? false

  const load = useCallback(async () => {
    onError(null)
    setLoading(true)
    try {
      const response = await apiGet<unknown>('/api/plugins/collectors')
      const parsed = collectorStatusListSchema.parse(response)
      setData(parsed)
      if (parsed.management_enabled) {
        const installedResponse = await apiGet<unknown>('/api/plugins/installed')
        setInstalled(installedPluginListSchema.parse(installedResponse))
      } else {
        setInstalled(null)
      }
    } catch (error) {
      onError(toErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void load()
  }, [load])

  // インストール中の配布物があるあいだだけポーリングする。
  const hasPendingInstall = (installed?.plugins ?? []).some(
    (plugin) => plugin.status === 'installing',
  )
  useEffect(() => {
    if (!hasPendingInstall) return undefined
    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const response = await apiGet<unknown>('/api/plugins/installed')
          setInstalled(installedPluginListSchema.parse(response))
        } catch {
          // ポーリングの失敗は次回に任せる（画面全体をエラーにしない）。
        }
      })()
    }, INSTALL_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [hasPendingInstall])

  const runMutation = useCallback(
    async (action: () => Promise<void>, successMessage?: string) => {
      onError(null)
      setNotice(null)
      setBusy(true)
      try {
        await action()
        if (successMessage) setNotice(successMessage)
      } catch (error) {
        onError(toErrorMessage(error))
      } finally {
        setBusy(false)
      }
    },
    [onError],
  )

  const saveCollector = useCallback(
    async (
      pluginId: string,
      values: { enabled?: boolean; interval_seconds?: number; timeout_seconds?: number },
    ) => {
      await runMutation(async () => {
        const response = await apiPatch<unknown>(
          `/api/plugins/collectors/${encodeURIComponent(pluginId)}`,
          values,
        )
        setData(collectorStatusListSchema.parse(response))
      }, '設定を保存しました。「変更を反映」で稼働中の構成に適用します。')
    },
    [runMutation],
  )

  const reload = useCallback(async () => {
    await runMutation(async () => {
      const response = await apiPost<unknown>('/api/plugins/collectors/reload', {})
      const parsed = collectorReloadSchema.parse(response)
      await load()
      setNotice(`レジストリを世代 ${parsed.generation} に更新しました。`)
    })
  }, [load, runMutation])

  const upload = useCallback(
    async (file: File) => {
      await runMutation(async () => {
        const form = new FormData()
        form.append('file', file)
        const response = await apiPostForm<unknown>('/api/plugins/installed/upload', form)
        setInstalled(installedPluginListSchema.parse(response))
      }, 'インストールを開始しました。')
    },
    [runMutation],
  )

  const installRequirement = useCallback(
    async (requirement: string) => {
      await runMutation(async () => {
        const response = await apiPost<unknown>('/api/plugins/installed', { requirement })
        setInstalled(installedPluginListSchema.parse(response))
      }, 'インストールを開始しました。')
    },
    [runMutation],
  )

  const uninstall = useCallback(
    async (distribution: string) => {
      await runMutation(async () => {
        await apiDelete(`/api/plugins/installed/${encodeURIComponent(distribution)}`)
        const response = await apiGet<unknown>('/api/plugins/installed')
        setInstalled(installedPluginListSchema.parse(response))
      }, 'アンインストールしました。「変更を反映」で稼働中の構成に適用します。')
    },
    [runMutation],
  )

  if (loading && data === null) {
    return <div className="loading">プラグイン一覧を読み込み中…</div>
  }

  return (
    <div className="panel plugin-management-panel">
      <p className="hint">
        {managementEnabled
          ? 'コレクタプラグインの構成と実行状態を確認し、有効/無効・実行間隔の変更やパッケージの追加ができます。変更は「変更を反映」を押すと稼働中の構成に適用されます（アプリの再起動は不要です）。'
          : 'コレクタプラグインの構成と実行状態を確認します。設定は TOML または環境変数で変更し、反映にはアプリの再起動が必要です。画面から変更するには VEA_PLUGIN_MANAGEMENT_ENABLED を有効にしてください。'}
      </p>

      {notice ? <p className="plugin-notice">{notice}</p> : null}

      {managementEnabled && data?.reload_required ? (
        <p className="plugin-reload-banner" role="status">
          未反映の変更があります。「変更を反映」を押すと稼働中の構成に適用されます。
        </p>
      ) : null}

      <div className="plugin-list-header">
        <h2>一覧</h2>
        <span className="plugin-generation">レジストリ世代 {data?.generation ?? '—'}</span>
        <button
          type="button"
          className="btn btn--gray"
          disabled={loading || busy}
          onClick={() => void load()}
        >
          {loading ? '更新中…' : '一覧を更新'}
        </button>
        {managementEnabled ? (
          <button type="button" className="btn" disabled={busy} onClick={() => void reload()}>
            {busy ? '処理中…' : '変更を反映'}
          </button>
        ) : null}
      </div>

      {data === null || data.collectors.length === 0 ? (
        <p className="no-data">プラグインは登録されていません。</p>
      ) : (
        <div className="plugin-table-container">
          <table className="table plugin-list-table">
            <thead>
              <tr>
                <th>プラグイン</th>
                <th>状態</th>
                <th>データ種別</th>
                <th>提供元</th>
                <th>バージョン</th>
                <th>実行間隔</th>
              </tr>
            </thead>
            <tbody>
              {data.collectors.map((collector) => {
                const expanded = expandedId === collector.id
                const detailsId = `plugin-details-${collector.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`
                const name = collector.display_name || collector.id
                return (
                  <Fragment key={collector.id}>
                    <tr className={expanded ? 'expanded-row' : undefined}>
                      <td>
                        <span className="plugin-name-cell">
                          <button
                            type="button"
                            className="btn btn--gray plugin-expand-button"
                            aria-expanded={expanded}
                            aria-controls={detailsId}
                            aria-label={expanded ? `${name} の詳細を閉じる` : `${name} の詳細を開く`}
                            onClick={() => setExpandedId(expanded ? null : collector.id)}
                          >
                            {expanded ? '▾' : '▸'}
                          </button>
                          <span>
                            <span className="plugin-display-name">{name}</span>
                            {collector.display_name ? (
                              <span className="plugin-metadata">{collector.id}</span>
                            ) : null}
                          </span>
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${collectorStatusClass(collector.status)}`}>
                          {COLLECTOR_STATUS_LABELS[collector.status] ?? collector.status}
                        </span>
                      </td>
                      <td>{dataKindsLabel(collector.data_kinds)}</td>
                      <td>{sourceLabel(collector.source)}</td>
                      <td>{collector.version || '—'}</td>
                      <td>{secondsLabel(collector.interval_seconds)}</td>
                    </tr>
                    {expanded ? (
                      <tr id={detailsId} className="plugin-detail-row">
                        <td colSpan={6}>
                          <dl className="plugin-detail-grid">
                            <div>
                              <dt>API バージョン</dt>
                              <dd>{collector.api_version ?? '—'}</dd>
                            </div>
                            <div>
                              <dt>タイムアウト</dt>
                              <dd>{secondsLabel(collector.timeout_seconds)}</dd>
                            </div>
                            <div>
                              <dt>登録元</dt>
                              <dd className="plugin-source-value">{collector.source}</dd>
                            </div>
                          </dl>
                          {collector.error ? (
                            <p className="plugin-configuration-error">
                              <strong>構成エラー:</strong> {collector.error}
                            </p>
                          ) : null}
                          {managementEnabled && collector.status !== 'failed' ? (
                            <CollectorSettingsForm
                              collector={collector}
                              disabled={busy}
                              onSave={(values) => saveCollector(collector.id, values)}
                            />
                          ) : null}
                          <h3>vCenter 別の実行状況</h3>
                          <RunsTable runs={collector.runs} timeZone={timeZone} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {managementEnabled ? (
        <InstalledPluginsSection
          data={installed}
          busy={busy}
          onUpload={upload}
          onInstallRequirement={installRequirement}
          onUninstall={uninstall}
          timeZone={timeZone}
        />
      ) : null}
    </div>
  )
}
