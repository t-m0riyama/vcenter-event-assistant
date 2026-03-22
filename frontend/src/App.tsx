import { lazy, Suspense, useState } from 'react'
import { TimeZoneProvider } from './datetime/TimeZoneProvider'
import { useAppConfig } from './hooks/useAppConfig'
import { AutoRefreshPreferencesProvider } from './preferences/AutoRefreshPreferencesProvider'
import { SummaryTopNotableMinScoreProvider } from './preferences/SummaryTopNotableMinScoreProvider'
import { EventsPanel } from './panels/events/EventsPanel'
import { GeneralSettingsPanel } from './panels/settings/GeneralSettingsPanel'
import { EventTypeGuidesPanel } from './panels/settings/EventTypeGuidesPanel'
import { ScoreRulesPanel } from './panels/settings/ScoreRulesPanel'
import { VCentersPanel } from './panels/settings/VCentersPanel'
import { SummaryPanel } from './panels/summary/SummaryPanel'
import { ThemeProvider } from './theme/ThemeProvider'
import './App.css'

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

type Tab = 'summary' | 'events' | 'metrics' | 'settings'

type SettingsSubTab = 'general' | 'vcenters' | 'score_rules' | 'event_type_guides'

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
              {(['summary', 'events', 'metrics', 'settings'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  className={tab === t ? 'active' : undefined}
                  onClick={() => {
                    setTab(t)
                    setErr(null)
                  }}
                >
                  {t === 'summary' && '概要'}
                  {t === 'events' && 'イベント'}
                  {t === 'metrics' && 'グラフ'}
                  {t === 'settings' && '設定'}
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
                    一般
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
                    vCenter
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
                    スコアルール
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
                    種別ガイド
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
            </main>
          </div>
        </SummaryTopNotableMinScoreProvider>
        </AutoRefreshPreferencesProvider>
      </TimeZoneProvider>
    </ThemeProvider>
  )
}
