import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { IncidentTimelineManualSnapshotListItem } from './api/schemas'
import { useAppConfig } from './hooks/useAppConfig'
import { useAttentionStatus } from './hooks/useAttentionStatus'
import { useAppTabHashSync } from './hooks/useAppTabHashSync'
import { parseAppHash } from './routing/appHashRouting'
import { EventsPanel } from './panels/events/EventsPanel'
import { ChatSamplePromptsPanel } from './panels/settings/ChatSamplePromptsPanel'
import { GeneralSettingsPanel } from './panels/settings/GeneralSettingsPanel'
import { EventTypeGuidesPanel } from './panels/settings/EventTypeGuidesPanel'
import { ScoreRulesPanel } from './panels/settings/ScoreRulesPanel'
import { VCentersPanel } from './panels/settings/VCentersPanel'
import { AlertRulesPanel } from './panels/settings/AlertRulesPanel'
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
import './App.css'

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

type MainTabConfig = {
  readonly id: MainTabId
  readonly label: string
  readonly panelLabel: string
  readonly render: (onError: (message: string | null) => void) => ReactNode
}

type SettingsSubTabConfig = {
  readonly id: SettingsSubTabId
  readonly label: string
  readonly panelLabel: string
  readonly render: (onError: (e: string | null) => void) => ReactNode
}

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
  const attention = useAttentionStatus()

  // タブに出すアテンションドット。概要=直近24hの要注意イベント、通知履歴=firing 中のアラート
  const tabAttention: Partial<Record<MainTabId, boolean>> = {
    summary: (attention?.notable_events_last_24h ?? 0) > 0,
    alerts: (attention?.firing_alerts ?? 0) > 0,
  }

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
        render: (onError) => <VCentersPanel onError={onError} />,
      },
      {
        id: 'score_rules',
        label: 'スコアルール',
        panelLabel: 'スコアルール',
        render: (onError) => <ScoreRulesPanel onError={onError} />,
      },
      {
        id: 'event_type_guides',
        label: 'イベント種別ガイド',
        panelLabel: 'イベント種別ガイド',
        render: (onError) => <EventTypeGuidesPanel onError={onError} />,
      },
      {
        id: 'alerts',
        label: 'アラート',
        panelLabel: 'アラート設定',
        render: (onError) => <AlertRulesPanel onError={onError} />,
      },
      {
        id: 'chat_samples',
        label: 'チャット',
        panelLabel: 'チャットサンプル',
        render: (onError) => <ChatSamplePromptsPanel onError={onError} />,
      },
    ],
    [],
  )

  const helpEntry = resolveTabHelp(tab, settingsSubTab)

  return (
    <AppProviders>
      <div className="app">
        <header className="header">
          <div className="header__row">
            <img src="/favicon.svg" alt="" className="header__logo" width={30} height={30} />
            <h1>vCenter Event Assistant</h1>
            <button
              type="button"
              className="help-toggle-button"
              onClick={() => setShowHelp(!showHelp)}
              aria-label="使い方を表示"
            >
              <HelpIcon />
              <span>使い方を表示</span>
            </button>
          </div>
          {retention && (
            <p className="retention-hint">
              データ保持: イベント {retention.event_retention_days} 日 / メトリクス{' '}
              {retention.metric_retention_days} 日（サーバー設定）
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
          {mainTabs.map((t) => (
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
                {settingsSubTabs.map((sub) => (
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
              {settingsSubTabs.map(
                (sub) =>
                  mountedSettingsSubTabs.has(sub.id) && (
                    <div
                      key={sub.id}
                      hidden={tab !== 'settings' || settingsSubTab !== sub.id}
                      aria-hidden={tab !== 'settings' || settingsSubTab !== sub.id}
                    >
                      <PanelShell panelLabel={sub.panelLabel}>
                        {(onError) => sub.render(onError)}
                      </PanelShell>
                    </div>
                  ),
              )}
            </div>
          )}

          {mainTabs.map(
            (t) =>
              mountedMainTabs.has(t.id) &&
              t.id !== 'settings' && (
                <div key={t.id} hidden={tab !== t.id} aria-hidden={tab !== t.id}>
                  <PanelShell panelLabel={t.panelLabel}>
                    {(onError) => t.render(onError)}
                  </PanelShell>
                </div>
              ),
          )}
        </main>
      </div>
    </AppProviders>
  )
}
