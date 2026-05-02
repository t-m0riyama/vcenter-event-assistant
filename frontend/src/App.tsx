import { lazy, Suspense, useState } from 'react'
import { useAppConfig } from './hooks/useAppConfig'
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
import { MainTabIcon, type MainTabId } from './components/main-tab-icons'
import { SettingsSubTabIcon, type SettingsSubTabId } from './components/settings-subtab-icons'
import { HelpIcon } from './components/help-icon'
import { AppProviders } from './components/AppProviders'
import './App.css'

const HELP_CONTENT: Record<string, string> = {
  summary:
    '【概要】\nシステムの稼働状況と最新の主要イベントを表示します。\n- 各種統計（イベント数、スコア別集計など）を確認できます。\n- スコアの高い「要注目イベント」を抽出して一覧表示します。',
  events:
    '【イベント一覧】\n取得したすべてのイベントを時系列で表示します。\n- 各種フィルタ（時間、vCenter、スコア、キーワード）で絞り込みが可能です。\n- 行を選択すると詳細を表示し、コメントを残すことができます。',
  metrics:
    '【グラフ】\nパフォーマンスメトリクスを可視化します。\n- ESXi ホストや仮想マシンの統計推移を確認できます。\n- 表示期間やリフレッシュ間隔を調整可能です。',
  digests:
    '【ダイジェスト】\nAI によるイベント要約を表示します。\n- 大量のイベントから要点を把握するのに便利です。\n- 指定した期間のサマリーを生成できます。',
  alerts:
    '【通知履歴】\nアラートの通知状況を確認できます。\n- 発火および回復のタイミング、通知の成否を一覧表示します。',
  chat:
    '【チャット】\nAI アシスタントと対話しながらイベント解析や調査が行えます。\n- 「最近の重要なエラーは？」などの質問が可能です。\n- サンプルプロンプトを活用して効率的に調査できます。',
  settings:
    '【設定】\nアプリケーションの動作環境を構成します。\n- 一般: リフレッシュ間隔やタイムゾーンの設定\n- vCenter: 接続先サーバーの管理\n- スコアルール: イベントの重要度判定ロジックの定義',
}

const MetricsPanel = lazy(async () => {
  const m = await import('./panels/metrics/MetricsPanel')
  return { default: m.MetricsPanel }
})

type Tab = MainTabId
type SettingsSubTab = SettingsSubTabId

type TabConfig = { id: Tab; label: string }

const MAIN_TABS: TabConfig[] = [
  { id: 'summary', label: '概要' },
  { id: 'events', label: 'イベント' },
  { id: 'metrics', label: 'グラフ' },
  { id: 'digests', label: 'ダイジェスト' },
  { id: 'alerts', label: '通知履歴' },
  { id: 'chat', label: 'チャット' },
  { id: 'settings', label: '設定' },
]

type SubTabConfig = { id: SettingsSubTab; label: string }

const SETTINGS_SUBTABS: SubTabConfig[] = [
  { id: 'general', label: '一般' },
  { id: 'vcenters', label: 'vCenter' },
  { id: 'score_rules', label: 'スコアルール' },
  { id: 'event_type_guides', label: 'イベント種別ガイド' },
  { id: 'alerts', label: 'アラート' },
  { id: 'chat_samples', label: 'チャット' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('summary')
  const [settingsSubTab, setSettingsSubTab] = useState<SettingsSubTab>('general')
  const [err, setErr] = useState<string | null>(null)
  const [showHelp, setShowHelp] = useState(false)
  const { retention } = useAppConfig(setErr)

  return (
    <AppProviders>
      <div className="app">
        <header className="header">
          <div style={{ display: 'flex', alignItems: 'center' }}>
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

        {err && (
          <div className="error-banner" role="alert">
            {err}
          </div>
        )}

        {showHelp && (
          <section className="help-section">
            <h2>
              <HelpIcon />
              <span>使い方ガイド</span>
            </h2>
            <p className="help-text">{HELP_CONTENT[tab]}</p>
          </section>
        )}

        <nav className="tabs">
          {MAIN_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? 'active' : undefined}
              onClick={() => {
                setTab(t.id)
                setShowHelp(false)
                setErr(null)
              }}
            >
              <span className="tab-button__inner">
                <MainTabIcon tabId={t.id} />
                <span className="tab-button__label">{t.label}</span>
              </span>
            </button>
          ))}
        </nav>

        <main className="main">
          {tab === 'settings' && (
            <nav className="settings-subtabs" aria-label="設定">
              {SETTINGS_SUBTABS.map((sub) => (
                <button
                  key={sub.id}
                  type="button"
                  className={settingsSubTab === sub.id ? 'active' : undefined}
                  aria-selected={settingsSubTab === sub.id}
                  onClick={() => {
                    setSettingsSubTab(sub.id)
                    setShowHelp(false)
                    setErr(null)
                  }}
                >
                  <span className="tab-button__inner">
                    <SettingsSubTabIcon tabId={sub.id} />
                    <span className="tab-button__label">{sub.label}</span>
                  </span>
                </button>
              ))}
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
          {tab === 'alerts' && <AlertHistoryPanel onError={setErr} />}
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
          {tab === 'settings' && settingsSubTab === 'alerts' && (
            <AlertRulesPanel onError={setErr} />
          )}
        </main>
      </div>
    </AppProviders>
  )
}
