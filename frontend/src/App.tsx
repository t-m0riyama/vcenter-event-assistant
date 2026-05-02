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
          {(['summary', 'events', 'metrics', 'digests', 'alerts', 'chat', 'settings'] as const).map(
            (t) => (
              <button
                key={t}
                type="button"
                className={tab === t ? 'active' : undefined}
                onClick={() => {
                  setTab(t)
                  setShowHelp(false)
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
                    {t === 'alerts' && '通知履歴'}
                    {t === 'chat' && 'チャット'}
                    {t === 'settings' && '設定'}
                  </span>
                </span>
              </button>
            ),
          )}
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
                  setShowHelp(false)
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
                  setShowHelp(false)
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
                  setShowHelp(false)
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
                  setShowHelp(false)
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
                className={settingsSubTab === 'alerts' ? 'active' : undefined}
                aria-selected={settingsSubTab === 'alerts'}
                onClick={() => {
                  setSettingsSubTab('alerts')
                  setShowHelp(false)
                  setErr(null)
                }}
              >
                <span className="tab-button__inner">
                  <SettingsSubTabIcon tabId="alerts" />
                  <span className="tab-button__label">アラート</span>
                </span>
              </button>
              <button
                type="button"
                className={settingsSubTab === 'chat_samples' ? 'active' : undefined}
                aria-selected={settingsSubTab === 'chat_samples'}
                onClick={() => {
                  setSettingsSubTab('chat_samples')
                  setShowHelp(false)
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
