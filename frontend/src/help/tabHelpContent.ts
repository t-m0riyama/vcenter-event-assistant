import type { MainTabId } from '../components/main-tab-icons'
import type { SettingsSubTabId } from '../components/settings-subtab-icons'

/** 利用者向けガイド（`docs/` 配下）への参照。リポジトリルートからの相対パス。 */
export type TabHelpEntry = {
  readonly summary: string
  /** 対応する Markdown のパス。未設定のタブはアプリ内要約のみ。 */
  readonly userGuideDoc?: string
  /** `<!-- vea-tab-help: ... -->` マーカー ID（乖離検知用）。 */
  readonly markerId?: string
}

/** メインタブごとの簡易ヘルプ（要約 + 利用者向けガイドへの対応）。 */
export const MAIN_TAB_HELP: Record<MainTabId, TabHelpEntry> = {
  summary: {
    summary:
      '【概要】\nシステムの稼働状況と最新の主要イベントを表示します。\n- 各種統計（イベント数、スコア別集計など）を確認できます。\n- スコアの高い「要注目イベント」を抽出して一覧表示します。',
    userGuideDoc: 'docs/user-guides/summary.md',
    markerId: 'summary',
  },
  events: {
    summary:
      '【イベント一覧】\n取得したすべてのイベントを時系列で表示します。\n- 各種フィルタ（時間、vCenter、スコア、キーワード）で絞り込みが可能です。\n- 行を選択すると詳細を表示し、コメントを残すことができます。',
    userGuideDoc: 'docs/user-guides/events.md',
    markerId: 'events',
  },
  metrics: {
    summary:
      '【グラフ】\nパフォーマンスメトリクスを可視化します。\n- ESXi ホストや仮想マシンの統計推移を確認できます。\n- 表示期間やリフレッシュ間隔を調整可能です。',
    userGuideDoc: 'docs/user-guides/graph.md',
    markerId: 'metrics',
  },
  digests: {
    summary:
      '【ダイジェスト】\nAI によるイベント要約を表示します。\n- 大量のイベントから要点を把握するのに便利です。\n- 指定した期間のサマリーを生成できます。',
    userGuideDoc: 'docs/user-guides/digests.md',
    markerId: 'digests',
  },
  alerts: {
    summary:
      '【通知履歴】\nアラートの通知状況を確認できます。\n- 発火および回復のタイミング、通知の成否を一覧表示します。',
    userGuideDoc: 'docs/user-guides/alerts.md',
    markerId: 'alerts',
  },
  chat: {
    summary:
      '【チャット】\nAI アシスタントと対話しながらイベント解析や調査が行えます。\n- 「最近の重要なエラーは？」などの質問が可能です。\n- サンプルプロンプトを活用して効率的に調査できます。',
    userGuideDoc: 'docs/user-guides/chat.md',
    markerId: 'chat',
  },
  timeline: {
    summary:
      '【タイムライン】\n指定期間のイベントとアラートを統合したインシデント時系列を生成します。\n- vCenter やメトリクス条件を指定して、調査に必要な情報を集約できます。\n- 表示された項目から異常の流れを時系列で確認できます。',
    userGuideDoc: 'docs/backend.md',
  },
  settings: {
    summary:
      '【設定】\nアプリケーションの動作環境を構成します。\n- 一般: リフレッシュ間隔やタイムゾーンの設定\n- vCenter: 接続先サーバーの管理\n- スコアルール: イベントの重要度判定ロジックの定義',
    userGuideDoc: 'docs/frontend.md',
  },
}

/** 設定サブタブごとの簡易ヘルプ（`settings` タブ表示時に優先）。 */
export const SETTINGS_SUB_TAB_HELP: Partial<Record<SettingsSubTabId, TabHelpEntry>> = {
  general: {
    summary:
      '【一般設定】\n表示タイムゾーン、自動更新間隔、要注意イベントの最小スコアなど、ブラウザローカルの表示設定を変更します。',
    userGuideDoc: 'docs/user-guides/summary.md',
    markerId: 'summary',
  },
  vcenters: {
    summary:
      '【vCenter 設定】\n接続先 vCenter の登録・編集・削除と接続テストを行います。',
    userGuideDoc: 'docs/frontend.md',
  },
  score_rules: {
    summary:
      '【スコアルール】\nイベント種別ごとの要注目スコア加算ルールを定義・インポートします。',
    userGuideDoc: 'docs/user-guides/score-rules.md',
    markerId: 'score_rules',
  },
  event_type_guides: {
    summary:
      '【イベント種別ガイド】\n運用向けの種別説明・推奨アクションを登録し、一覧や詳細に反映します。',
    userGuideDoc: 'docs/frontend.md',
  },
  alerts: {
    summary:
      '【アラート設定】\nメール通知ルール（イベントスコア・メトリクス閾値）の作成と有効化を行います。',
    userGuideDoc: 'docs/user-guides/alerts.md',
    markerId: 'alerts',
  },
  chat_samples: {
    summary:
      '【チャットサンプル】\nチャット画面から挿入できるサンプル質問を編集・インポートします。',
    userGuideDoc: 'docs/user-guides/chat.md',
    markerId: 'chat',
  },
}

/**
 * 現在のタブに応じたヘルプエントリを返す。
 * 設定タブではサブタブ用エントリを優先する。
 */
export function resolveTabHelp(tab: MainTabId, settingsSubTab: SettingsSubTabId): TabHelpEntry {
  if (tab === 'settings') {
    return SETTINGS_SUB_TAB_HELP[settingsSubTab] ?? MAIN_TAB_HELP.settings
  }
  return MAIN_TAB_HELP[tab]
}
