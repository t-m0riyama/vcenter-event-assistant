import { lazy, Suspense, useState } from 'react'
import { TimeZoneProvider } from './datetime/TimeZoneProvider'
import { useAppConfig } from './hooks/useAppConfig'
import { AutoRefreshPreferencesProvider } from './preferences/AutoRefreshPreferencesProvider'
import { ChatMaxStoredMessagesProvider } from './preferences/ChatMaxStoredMessagesProvider'
import { ChatSamplePromptsProvider } from './preferences/ChatSamplePromptsProvider'
import { SummaryTopNotableMinScoreProvider } from './preferences/SummaryTopNotableMinScoreProvider'
import { EventsPanel } from './panels/events/EventsPanel'
import { ChatSamplePromptsPanel } from './panels/settings/ChatSamplePromptsPanel'
import { GeneralSettingsPanel } from './panels/settings/GeneralSettingsPanel'
import { EventTypeGuidesPanel } from './panels/settings/EventTypeGuidesPanel'
import { ScoreRulesPanel } from './panels/settings/ScoreRulesPanel'
import { VCentersPanel } from './panels/settings/VCentersPanel'
import { ChatPanel } from './panels/chat/ChatPanel'
import { DigestsPanel } from './panels/digests/DigestsPanel'
import { SummaryPanel } from './panels/summary/SummaryPanel'
import { ThemeProvider } from './theme/ThemeProvider'
import { MainTabIcon, type MainTabId } from './components/main-tab-icons'
import { SettingsSubTabIcon, type SettingsSubTabId } from './components/settings-subtab-icons'
import './App.css'

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

type Tab = MainTabId

type SettingsSubTab = SettingsSubTabId

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('general')
  const [err, setErr] = useState<string | null>(null)
  const { retention } = useAppConfig(setErr)

  return (
    <ThemeProvider>
      <TimeZoneProvider>
        <AutoRefreshPreferencesProvider>
          <SummaryTopNotableMinScoreProvider>
            <ChatMaxStoredMessagesProvider>
              <ChatSamplePromptsProvider>
                <div className="app">
                  <header className="header">
                    <h1>vCenter Event Assistant</h1>
                    {retention && (
                      <p className="retention-hint">
                        データ保持: イベント {retention.event_retention_days} 日 / メトリクス{' '}
                        {retention.metric_retention_days} 日（サーバー設定）
                      </p>
                    )}
                  </header>

                  {err && (
                    <div className="error-banner" role="alert">
                      {err}
                    </div>
                  )}

                  <nav className="tabs">
                    {(['summary', 'events', 'metrics', 'digests', 'chat', 'settings'] as const).map((t) => (
                      <button
                        key={t}
                        type="button"
                        className={tab === t ? 'active' : undefined}
                        onClick={() => {
                          setTab(t)
                          setErr(null)
                        }}
                      >
                        <span className="tab-button__inner">
                          <MainTabIcon tabId={t} />
                          <span className="tab-button__label">
                            {t === 'summary' && '概要'}
                            {t === 'events' && 'イベント'}
                            {t === 'metrics' && 'グラフ'}
                            {t === 'digests' && 'ダイジェスト'}
                            {t === 'chat' && 'チャット'}
                            {t === 'settings' && '設定'}
                          </span>
                        </span>
                      </button>
                    ))}
                  </nav>

                  <main className="main">
                    {tab === 'settings' && (
                      <nav className="settings-subtabs" aria-label="設定">
                        <button
                          type="button"
                          className={settingsSubTab === 'general' ? 'active' : undefined}
                          aria-selected={settingsSubTab === 'general'}
                          onClick={() => {
                            setSettingsSubTab('general')
                            setErr(null)
                          }}
                        >
                          <span className="tab-button__inner">
                            <SettingsSubTabIcon tabId="general" />
                            <span className="tab-button__label">一般</span>
                          </span>
                        </button>
                        <button
                          type="button"
                          className={settingsSubTab === 'vcenters' ? 'active' : undefined}
                          aria-selected={settingsSubTab === 'vcenters'}
                          onClick={() => {
                            setSettingsSubTab('vcenters')
                            setErr(null)
                          }}
                        >
                          <span className="tab-button__inner">
                            <SettingsSubTabIcon tabId="vcenters" />
                            <span className="tab-button__label">vCenter</span>
                          </span>
                        </button>
                        <button
                          type="button"
                          className={settingsSubTab === 'score_rules' ? 'active' : undefined}
                          aria-selected={settingsSubTab === 'score_rules'}
                          onClick={() => {
                            setSettingsSubTab('score_rules')
                            setErr(null)
                          }}
                        >
                          <span className="tab-button__inner">
                            <SettingsSubTabIcon tabId="score_rules" />
                            <span className="tab-button__label">スコアルール</span>
                          </span>
                        </button>
                        <button
                          type="button"
                          className={settingsSubTab === 'event_type_guides' ? 'active' : undefined}
                          aria-selected={settingsSubTab === 'event_type_guides'}
                          onClick={() => {
                            setSettingsSubTab('event_type_guides')
                            setErr(null)
                          }}
                        >
                          <span className="tab-button__inner">
                            <SettingsSubTabIcon tabId="event_type_guides" />
                            <span className="tab-button__label">イベント種別ガイド</span>
                          </span>
                        </button>
                        <button
                          type="button"
                          className={settingsSubTab === 'chat_samples' ? 'active' : undefined}
                          aria-selected={settingsSubTab === 'chat_samples'}
                          onClick={() => {
                            setSettingsSubTab('chat_samples')
                            setErr(null)
                          }}
                        >
                          <span className="tab-button__inner">
                            <SettingsSubTabIcon tabId="chat_samples" />
                            <span className="tab-button__label">チャット</span>
                          </span>
                        </button>
                      </nav>
                    )}
                    {tab === 'summary' && <SummaryPanel onError={setErr} />}
                    {tab === 'events' && <EventsPanel onError={setErr} />}
                    {tab === 'metrics' && (
                      <Suspense fallback={<p className="hint">グラフを読み込み中…</p>}>
                        <MetricsPanel
                          onError={setErr}
                          perfBucketSeconds={retention?.perf_sample_interval_seconds ?? 300}
                        />
                      </Suspense>
                    )}
                    {tab === 'digests' && <DigestsPanel onError={setErr} />}
                    {tab === 'chat' && <ChatPanel onError={setErr} />}
                    {tab === 'settings' && settingsSubTab === 'general' && <GeneralSettingsPanel />}
                    {tab === 'settings' && settingsSubTab === 'score_rules' && (
                      <ScoreRulesPanel onError={setErr} />
                    )}
                    {tab === 'settings' && settingsSubTab === 'event_type_guides' && (
                      <EventTypeGuidesPanel onError={setErr} />
                    )}
                    {tab === 'settings' && settingsSubTab === 'vcenters' && (
                      <VCentersPanel onError={setErr} />
                    )}
                    {tab === 'settings' && settingsSubTab === 'chat_samples' && (
                      <ChatSamplePromptsPanel onError={setErr} />
                    )}
                  </main>
                </div>
              </ChatSamplePromptsProvider>
            </ChatMaxStoredMessagesProvider>
          </SummaryTopNotableMinScoreProvider>
        </AutoRefreshPreferencesProvider>
      </TimeZoneProvider>
    </ThemeProvider>
  )
}
