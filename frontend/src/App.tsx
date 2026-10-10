import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { IncidentTimelineManualSnapshotListItem } from './api/schemas'
import { useAppConfig } from './hooks/useAppConfig'
import { useAttentionStatus } from './hooks/useAttentionStatus'
import { useAppTabHashSync } from './hooks/useAppTabHashSync'
import { parseAppHash } from './routing/appHashRouting'
import { LogsPanel } from './panels/logs/LogsPanel'
import { EventsPanel } from './panels/events/EventsPanel'
import { ChatSamplePromptsPanel } from './panels/settings/ChatSamplePromptsPanel'
import { ChatWebSearchPrefsPanel } from './panels/settings/ChatWebSearchPrefsPanel'
import { GeneralSettingsPanel } from './panels/settings/GeneralSettingsPanel'
import { EventTypeGuidesPanel } from './panels/settings/EventTypeGuidesPanel'
import { ScoreRulesPanel } from './panels/settings/ScoreRulesPanel'
import { DirectoriesPanel } from './panels/settings/DirectoriesPanel'
import { UsersPanel } from './panels/settings/UsersPanel'
import { VCentersPanel } from './panels/settings/VCentersPanel'
import { AlertRulesPanel } from './panels/settings/AlertRulesPanel'
import { PluginsPanel } from './panels/settings/PluginsPanel'
import { ChatPanel } from './panels/chat/ChatPanel'
import { DigestsPanel } from './panels/digests/DigestsPanel'
import { AlertHistoryPanel } from './panels/alerts/AlertHistoryPanel'
import { SummaryPanel } from './panels/summary/SummaryPanel'
import { TimelinePanel } from './panels/timeline/TimelinePanel'
import { MainTabIcon, type MainTabId } from './components/main-tab-icons'
import { SettingsSubTabIcon, type SettingsSubTabId } from './components/settings-subtab-icons'
import { HelpIcon } from './components/help-icon'
import { TabHelpSection } from './components/TabHelpSection'
import { AppProviders } from './components/AppProviders'
import { PanelShell } from './components/PanelErrorBoundary'
import { resolveTabHelp } from './help/tabHelpContent'
import { UserMenu } from './auth/UserMenu'
import { useAuth } from './auth/useAuth'
import './App.css'

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

type MainTabConfig = {
  readonly id: MainTabId
  readonly label: string
  readonly panelLabel: string
  readonly render: (onError: (message: string | null) => void, active: boolean) => ReactNode
}

type SettingsSubTabConfig = {
  readonly id: SettingsSubTabId
  readonly label: string
  readonly panelLabel: string
  /** ``active`` はこのサブタブが表示中か（開き直したときに読み直すパネル用）。 */
  readonly render: (onError: (e: string | null) => void, active: boolean) => ReactNode
  /**
   * サーバに保存する設定で、admin 以外には閲覧専用で見せるもの（お知らせを出す）。
   * 変更系の操作部品はパネル自身がロールで出し分ける（展開など閲覧の操作は残す。ファイルへのエクスポートは operator 以上）。
   */
  readonly adminOnlyEdit?: boolean
}

/** 認証の管理（admin のみ、認証が有効なときだけ出す）の設定サブタブ。 */
const AUTH_ADMIN_SUB_TABS: ReadonlySet<SettingsSubTabId> = new Set(['users', 'directories'])

function initialMountedMainTabs(): Set<MainTabId> {
  return new Set([parseAppHash(window.location.hash).tab])
}

function initialMountedSettingsSubTabs(): Set<SettingsSubTabId> {
  const parsed = parseAppHash(window.location.hash)
  return parsed.tab === 'settings' ? new Set([parsed.settingsSubTab]) : new Set()
}

/** アプリのルート。メインタブと設定サブタブで各パネルを切り替える。 */
export default function App() {
  const { tab, setTab, settingsSubTab, setSettingsSubTab } = useAppTabHashSync()
  const [mountedMainTabs, setMountedMainTabs] = useState<Set<MainTabId>>(initialMountedMainTabs)
  const [mountedSettingsSubTabs, setMountedSettingsSubTabs] = useState<Set<SettingsSubTabId>>(
    initialMountedSettingsSubTabs,
  )
  const [metricsSnapshotReplay, setMetricsSnapshotReplay] =
    useState<IncidentTimelineManualSnapshotListItem | null>(null)
  const [metricsReplayNonce, setMetricsReplayNonce] = useState(0)
  const [appErr, setAppErr] = useState<string | null>(null)
  const [showHelp, setShowHelp] = useState(false)
  const { retention } = useAppConfig(setAppErr)
  const { me, hasRole } = useAuth()
  const canChat = hasRole('operator')
  const isAdmin = hasRole('admin')
  // ユーザー管理と認証ディレクトリは admin のみ。認証が無効なサーバではログインがないので出さない
  const canManageUsers = isAdmin && me.auth_enabled
  const attention = useAttentionStatus()

  // タブに出すアテンションドット。概要=直近24hの要注意イベント、通知履歴=firing 中のアラート
  const tabAttention: Partial<Record<MainTabId, boolean>> = {
    summary: (attention?.notable_events_last_24h ?? 0) > 0,
    alerts: (attention?.firing_alerts ?? 0) > 0,
  }

  useEffect(() => {
    // 権限のないタブ（URL の直接指定など）は概要に戻す
    if (tab === 'chat' && !canChat) {
      setTab('summary')
    }
  }, [canChat, setTab, tab])

  useEffect(() => {
    if (tab === 'settings' && AUTH_ADMIN_SUB_TABS.has(settingsSubTab) && !canManageUsers) {
      setSettingsSubTab('general')
    }
  }, [canManageUsers, setSettingsSubTab, settingsSubTab, tab])

  useEffect(() => {
    if (tab !== 'metrics') {
      setMetricsSnapshotReplay(null)
    }
  }, [tab])

  const ensureMainTabMounted = (id: MainTabId) => {
    setMountedMainTabs((prev) => (prev.has(id) ? prev : new Set(prev).add(id)))
  }

  const ensureSettingsSubTabMounted = (id: SettingsSubTabId) => {
    ensureMainTabMounted('settings')
    setMountedSettingsSubTabs((prev) => (prev.has(id) ? prev : new Set(prev).add(id)))
  }

  useEffect(() => {
    ensureMainTabMounted(tab)
    if (tab === 'settings') {
      ensureSettingsSubTabMounted(settingsSubTab)
    }
    // hashchange 等で tab が変わったときもマウントを追従させる
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsSubTab, tab])

  const selectMainTab = (next: MainTabId) => {
    ensureMainTabMounted(next)
    setTab(next)
    setShowHelp(false)
  }

  const selectSettingsSubTab = (next: SettingsSubTabId) => {
    ensureSettingsSubTabMounted(next)
    setSettingsSubTab(next)
    setShowHelp(false)
  }

  const mainTabs: MainTabConfig[] = useMemo(
    () => [
      {
        id: 'summary',
        label: '概要',
        panelLabel: '概要',
        render: (onError) => <SummaryPanel onError={onError} />,
      },
      {
        id: 'events',
        label: 'イベント',
        panelLabel: 'イベント一覧',
        render: (onError) => <EventsPanel onError={onError} />,
      },
      {
        id: 'logs',
        label: 'ログ',
        panelLabel: 'ログ検索',
        render: (onError, active) => <LogsPanel onError={onError} active={active} />,
      },
      {
        id: 'metrics',
        label: 'グラフ',
        panelLabel: 'グラフ',
        render: (onError) => (
          <Suspense fallback={<p className="hint">グラフを読み込み中…</p>}>
            <MetricsPanel
              onError={onError}
              perfBucketSeconds={retention?.perf_sample_interval_seconds ?? 300}
              snapshotReplay={
                metricsSnapshotReplay
                  ? { item: metricsSnapshotReplay, nonce: metricsReplayNonce }
                  : null
              }
            />
          </Suspense>
        ),
      },
      {
        id: 'digests',
        label: 'ダイジェスト',
        panelLabel: 'ダイジェスト',
        render: (onError) => <DigestsPanel onError={onError} />,
      },
      {
        id: 'alerts',
        label: '通知履歴',
        panelLabel: '通知履歴',
        render: (onError) => <AlertHistoryPanel onError={onError} />,
      },
      {
        id: 'chat',
        label: 'チャット',
        panelLabel: 'チャット',
        render: (onError) => <ChatPanel onError={onError} />,
      },
      {
        id: 'timeline',
        label: 'タイムライン',
        panelLabel: 'タイムライン',
        render: (onError) => (
          <TimelinePanel
            onError={onError}
            onOpenSnapshotInMetrics={(item) => {
              setMetricsSnapshotReplay(item)
              setMetricsReplayNonce((n) => n + 1)
              ensureMainTabMounted('metrics')
              setTab('metrics')
              setShowHelp(false)
            }}
          />
        ),
      },
    ],
    [metricsReplayNonce, metricsSnapshotReplay, retention?.perf_sample_interval_seconds, setTab],
  )
  // チャットは operator 以上（LLM の呼び出しを伴うため）
  const visibleMainTabs = mainTabs.filter((t) => t.id !== 'chat' || canChat)

  const settingsSubTabs: SettingsSubTabConfig[] = useMemo(
    () => [
      {
        id: 'general',
        label: '一般',
        panelLabel: '一般設定',
        render: () => <GeneralSettingsPanel />,
      },
      {
        id: 'vcenters',
        label: 'vCenter',
        panelLabel: 'vCenter 設定',
        adminOnlyEdit: true,
        render: (onError) => <VCentersPanel onError={onError} />,
      },
      {
        id: 'score_rules',
        label: 'スコアルール',
        panelLabel: 'スコアルール',
        adminOnlyEdit: true,
        render: (onError) => <ScoreRulesPanel onError={onError} />,
      },
      {
        id: 'event_type_guides',
        label: 'イベント種別ガイド',
        panelLabel: 'イベント種別ガイド',
        adminOnlyEdit: true,
        render: (onError) => <EventTypeGuidesPanel onError={onError} />,
      },
      {
        id: 'alerts',
        label: 'アラート',
        panelLabel: 'アラート設定',
        adminOnlyEdit: true,
        render: (onError) => <AlertRulesPanel onError={onError} />,
      },
      {
        id: 'plugins',
        label: 'プラグイン',
        panelLabel: 'プラグイン管理',
        adminOnlyEdit: true,
        render: (onError) => <PluginsPanel onError={onError} />,
      },
      {
        id: 'users',
        label: 'ユーザー',
        panelLabel: 'ユーザー管理',
        render: (onError, active) => <UsersPanel onError={onError} active={active} />,
      },
      {
        id: 'directories',
        label: '認証ディレクトリ',
        panelLabel: '認証ディレクトリ',
        render: (onError, active) => <DirectoriesPanel onError={onError} active={active} />,
      },
      {
        id: 'chat_samples',
        label: 'チャット',
        panelLabel: 'チャット設定',
        render: (onError) => (
          <>
            <ChatSamplePromptsPanel onError={onError} />
            <ChatWebSearchPrefsPanel />
          </>
        ),
      },
    ],
    [],
  )

  const visibleSettingsSubTabs = settingsSubTabs.filter(
    (sub) => !AUTH_ADMIN_SUB_TABS.has(sub.id) || canManageUsers,
  )

  const helpEntry = resolveTabHelp(tab, settingsSubTab)

  return (
    <AppProviders>
      <div className="app">
        <header className="header">
          <div className="header__row">
            <img src="/favicon-small-light.svg" alt="" className="header__logo header__logo--light" width={44} height={44} />
            <img src="/favicon-small.svg" alt="" className="header__logo header__logo--dark" width={44} height={44} />
            <h1>vCenter Event Assistant</h1>
            <div className="header__actions">
              <button
                type="button"
                className="help-toggle-button"
                onClick={() => setShowHelp(!showHelp)}
                aria-label="使い方を表示"
              >
                <HelpIcon />
                <span>使い方を表示</span>
              </button>
              <UserMenu />
            </div>
          </div>
          {retention && (
            <p className="retention-hint">
              データ保持: イベント {retention.event_retention_days} 日 / メトリクス{' '}
              {retention.metric_retention_days} 日 / ログ {retention.log_retention_days} 日（サーバー設定）
            </p>
          )}
          {retention?.mock_mode === true && (
            <p className="mock-mode-banner" role="status">
              モックモード: 外部サービス（vCenter / SMTP / LLM / WEB 検索）には接続しません
            </p>
          )}
        </header>

        {appErr && (
          <div className="error-banner app-error-banner" role="alert">
            {appErr}
          </div>
        )}

        {showHelp && <TabHelpSection entry={helpEntry} />}

        <nav className="tabs">
          {visibleMainTabs.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? 'active' : undefined}
              onClick={() => selectMainTab(t.id)}
            >
              <span className="tab-button__inner">
                <MainTabIcon tabId={t.id} />
                <span className="tab-button__label">{t.label}</span>
                {tabAttention[t.id] && (
                  <span className="tab-attention-dot" title="要注意の項目があります">
                    <span className="visually-hidden">（要注意あり）</span>
                  </span>
                )}
              </span>
            </button>
          ))}
          <button
            key="settings"
            type="button"
            className={tab === 'settings' ? 'active' : undefined}
            onClick={() => selectMainTab('settings')}
          >
            <span className="tab-button__inner">
              <MainTabIcon tabId="settings" />
              <span className="tab-button__label">設定</span>
            </span>
          </button>
        </nav>

        <main className="main">
          {mountedMainTabs.has('settings') && (
            <div hidden={tab !== 'settings'} aria-hidden={tab !== 'settings'}>
              <nav className="settings-subtabs" aria-label="設定">
                {visibleSettingsSubTabs.map((sub) => (
                  <button
                    key={sub.id}
                    type="button"
                    className={settingsSubTab === sub.id ? 'active' : undefined}
                    aria-selected={settingsSubTab === sub.id}
                    onClick={() => selectSettingsSubTab(sub.id)}
                  >
                    <span className="tab-button__inner">
                      <SettingsSubTabIcon tabId={sub.id} />
                      <span className="tab-button__label">{sub.label}</span>
                    </span>
                  </button>
                ))}
              </nav>
              {visibleSettingsSubTabs.map(
                (sub) =>
                  mountedSettingsSubTabs.has(sub.id) && (
                    <div
                      key={sub.id}
                      hidden={tab !== 'settings' || settingsSubTab !== sub.id}
                      aria-hidden={tab !== 'settings' || settingsSubTab !== sub.id}
                    >
                      <PanelShell panelLabel={sub.panelLabel}>
                        {(onError) =>
                          sub.adminOnlyEdit && !isAdmin ? (
                            <>
                              <p className="readonly-notice" role="note">
                                閲覧のみです。この設定を変更できるのは管理者だけです。
                              </p>
                              {sub.render(onError, tab === 'settings' && settingsSubTab === sub.id)}
                            </>
                          ) : (
                            sub.render(onError, tab === 'settings' && settingsSubTab === sub.id)
                          )
                        }
                      </PanelShell>
                    </div>
                  ),
              )}
            </div>
          )}

          {visibleMainTabs.map(
            (t) =>
              mountedMainTabs.has(t.id) &&
              t.id !== 'settings' && (
                <div key={t.id} hidden={tab !== t.id} aria-hidden={tab !== t.id}>
                  <PanelShell panelLabel={t.panelLabel}>
                    {(onError) => t.render(onError, tab === t.id)}
                  </PanelShell>
                </div>
              ),
          )}
        </main>
      </div>
    </AppProviders>
  )
}
