import { useState } from 'react'
import { TimeZoneProvider } from './datetime/TimeZoneProvider'
import { useAppConfig } from './hooks/useAppConfig'
import { EventsPanel } from './panels/events/EventsPanel'
import { MetricsPanel } from './panels/metrics/MetricsPanel'
import { GeneralSettingsPanel } from './panels/settings/GeneralSettingsPanel'
import { ScoreRulesPanel } from './panels/settings/ScoreRulesPanel'
import { VCentersPanel } from './panels/settings/VCentersPanel'
import { SummaryPanel } from './panels/summary/SummaryPanel'
import { ThemeProvider } from './theme/ThemeProvider'
import './App.css'

type Tab = 'summary' | 'events' | 'metrics' | 'settings'

type SettingsSubTab = 'general' | 'vcenters' | 'score_rules'

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('general')
  const [err, setErr] = useState<string | null>(null)
  const { retention } = useAppConfig(setErr)

  return (
    <ThemeProvider>
      <TimeZoneProvider>
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
              </nav>
            )}
            {tab === 'summary' && <SummaryPanel onError={setErr} />}
            {tab === 'events' && <EventsPanel onError={setErr} />}
            {tab === 'metrics' && (
              <MetricsPanel
                onError={setErr}
                perfBucketSeconds={retention?.perf_sample_interval_seconds ?? 300}
              />
            )}
            {tab === 'settings' && settingsSubTab === 'general' && <GeneralSettingsPanel />}
            {tab === 'settings' && settingsSubTab === 'score_rules' && (
              <ScoreRulesPanel onError={setErr} />
            )}
            {tab === 'settings' && settingsSubTab === 'vcenters' && (
              <VCentersPanel onError={setErr} />
            )}
          </main>
        </div>
      </TimeZoneProvider>
    </ThemeProvider>
  )
}
