import { Fragment, useCallback, useEffect, useState } from 'react'

import { apiGet } from '../../api'
import {
  collectorStatusListSchema,
  type CollectorRunStatus,
  type CollectorStatusList,
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

/** コレクタプラグインの構成と最新実行状態を表示する読み取り専用パネル。 */
export function PluginsPanel({ onError }: { readonly onError: (message: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [data, setData] = useState<CollectorStatusList | null>(null)
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    onError(null)
    setLoading(true)
    try {
      const response = await apiGet<unknown>('/api/plugins/collectors')
      setData(collectorStatusListSchema.parse(response))
    } catch (error) {
      onError(toErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [onError])

  useEffect(() => {
    void load()
  }, [load])

  if (loading && data === null) {
    return <div className="loading">プラグイン一覧を読み込み中…</div>
  }

  return (
    <div className="panel plugin-management-panel">
      <p className="hint">
        コレクタプラグインの構成と実行状態を確認します。設定は TOML または環境変数で変更し、反映にはアプリの再起動が必要です。
      </p>

      <div className="plugin-list-header">
        <h2>一覧</h2>
        <span className="plugin-generation">レジストリ世代 {data?.generation ?? '—'}</span>
        <button
          type="button"
          className="btn btn--gray"
          disabled={loading}
          onClick={() => void load()}
        >
          {loading ? '更新中…' : '一覧を更新'}
        </button>
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
    </div>
  )
}
