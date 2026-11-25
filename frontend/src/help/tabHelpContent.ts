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
      '【概要】\nシステムの稼働状況と最新の主要イベントを表示します。\n- 各種統計（イベント数、スコア別集計など）を確認できます。\n- スコアの高い「要注目イベント」を抽出して一覧表示します。\n- イベントや CPU・メモリの行の「タイムラインで見る」から、その時刻を起点にタイムラインを開けます。',
    userGuideDoc: 'docs/userguide/summary.md',
    markerId: 'summary',
  },
  events: {
    summary:
      '【イベント一覧】\n取得したすべてのイベントを時系列で表示します。\n- 各種フィルタ（時間、vCenter、スコア、キーワード）で絞り込みが可能です。\n- 行を選択すると詳細を表示し、コメントを残すことができます。\n- 行の「タイムラインで見る」から、そのイベントの時刻を起点に、同じ vCenter・対象でタイムラインを開き、前後の出来事を確認できます。',
    userGuideDoc: 'docs/userguide/events.md',
    markerId: 'events',
  },
  logs: {
    summary: "【ログ検索】\nSSHで収集したログを期間・接続先・種別・重大度・本文で検索します。未解析の発生時刻は取得時刻で表示します。イベントの前後5分のログへ移動できます。\n- 「型ごと」では、開始と終了を指定した期間のログを、数値や ID などを伏せた型ごとに集計します。行を選ぶと、その型と vCenter で絞った一覧と CSV を利用できます。",
    userGuideDoc: "docs/userguide/remote-log-collector.md",
  },
  metrics: {
    summary:
      '【グラフ】\nパフォーマンスメトリクスを可視化します。\n- ESXi ホストや仮想マシンの統計推移を確認できます。\n- 表示期間やリフレッシュ間隔を調整可能です。',
    userGuideDoc: 'docs/userguide/graph.md',
    markerId: 'metrics',
  },
  digests: {
    summary:
      '【ダイジェスト】\nAI によるイベント要約を表示します。\n- 大量のイベントから要点を把握するのに便利です。\n- 指定した期間のサマリーを生成できます。',
    userGuideDoc: 'docs/userguide/digests.md',
    markerId: 'digests',
  },
  alerts: {
    summary:
      '【通知履歴】\nアラートの通知状況を確認できます。\n- 発火および回復のタイミング、通知の成否を一覧表示します。\n- 行の「タイムラインで見る」から、その時刻を起点に、同じ vCenter・対象でタイムラインを開き、前後の出来事を確認できます。',
    userGuideDoc: 'docs/userguide/alerts.md',
    markerId: 'alerts',
  },
  chat: {
    summary:
      '【チャット】\nAI アシスタントと対話しながらイベント解析や調査が行えます。\n- 「最近の重要なエラーは？」などの質問が可能です。\n- サンプルプロンプトを活用して効率的に調査できます。',
    userGuideDoc: 'docs/userguide/chat.md',
    markerId: 'chat',
  },
  timeline: {
    summary:
      '【タイムライン】\n障害の初動で、何が・どこで・どの順に起きたかを見る画面です。開くと直近 1 時間を表示します。\n- 期間と起点: 直近 1 / 6 / 24 時間か、開始・終了で期間を決めます。行の「ここを起点にする」で起点を決めると、「起点の前後 15 分 / 1 時間 / 6 時間」で絞れます。\n- 絞り込み: vCenter・対象（ホスト・VM 名）・種別（イベント / アラート / メトリクス / ログ）を変えると読み直します。「詳細設定」で最小スコアと、CPU・メモリ使用率のしきい値を変えられます。\n- 件数の俯瞰: 棒は件数、破線はエラーログ、下の帯はメトリクスがしきい値以上だった区間です。クリックやドラッグで期間を絞れます。\n- ハイライト: 最初の兆候、影響の大きい対象、直前の期間には無かったイベント種別、検知した障害パターン、起点までの構成変更を表示します。起点が無いときは、期間の終わりまでの構成変更を表示します。「初めて警告以上で出たログの型」からは、最初の時刻を起点にしたり、同じ型・vCenter・期間で絞ったログ一覧を開いたりできます。\n- 行を開くと、メッセージ全文とイベント種別ガイド、「この対象で絞る」「ここを起点にする」「イベントで開く」「ログで開く」「グラフで開く」が使えます。\n- 件数が多いときは、重要度の高い行（起点があるときは起点に近い行）を残します。件数が多すぎる種別は一覧から省き、その旨を表示します。詳しくはユーザーガイドを参照してください。\n- スナップショット: 条件と、保存した時点の結果を保存します。元のデータが保持期間を過ぎても、スナップショットの保持期間のあいだは保存した内容を見られます（「イベントで開く」などの先は空になります）。\n- 「この範囲をチャットで分析」（operator 以上）: 表示中の期間と vCenter をチャットに渡します。対象・種別・起点・最小スコア・しきい値は渡らず、チャットは現在のデータで集計します。メッセージは自動では送りません。',
    userGuideDoc: 'docs/userguide/timeline.md',
    markerId: 'timeline',
  },
  incidents: {
    summary:
      '【インシデント】\n障害の状態・担当・経過と、関係するイベント・通知・スナップショットをまとめて記録します。\n- 一覧の既定は未解決です。状態と件名で絞り込めます。\n- イベント・通知履歴・タイムラインの「インシデントに追加」から、既存の記録に紐付けるか、新しく作れます。\n- 紐付けたイベントと通知は写しが残ります。スナップショットは保存した結果をタイムラインで開いたり、調査資料を出力したりできます。\n- 「対応手順」では、紐付けたイベントや通知から候補を表示します。診断が有効なら admin は対象と SSH 接続先、送るコマンドをプレビューして実行できます。保存済みの「診断の結果」は viewer 以上が開けます。\n- 作成・編集・紐付け・メモの追加は operator 以上、インシデントと経過の削除は admin のみです。',
    userGuideDoc: 'docs/userguide/incidents.md',
    markerId: 'incidents',
  },
  settings: {
    summary:
      '【設定】\nアプリケーションの動作環境を構成します。\n- 一般: リフレッシュ間隔やタイムゾーンの設定\n- vCenter: 接続先サーバーの管理\n- スコアルール: イベントの重要度判定ロジックの定義\n- プラグイン: コレクタの構成と実行状態の確認',
    userGuideDoc: 'docs/development/frontend.md',
  },
}

/** 設定サブタブごとの簡易ヘルプ（`settings` タブ表示時に優先）。 */
export const SETTINGS_SUB_TAB_HELP: Partial<Record<SettingsSubTabId, TabHelpEntry>> = {
  general: {
    summary:
      '【一般設定】\n表示タイムゾーン、自動更新間隔、要注意イベントの最小スコアなど、ブラウザローカルの表示設定を変更します。',
    userGuideDoc: 'docs/userguide/summary.md',
    markerId: 'summary',
  },
  vcenters: {
    summary:
      '【vCenter 設定】\n接続先 vCenter の登録・編集・削除と接続テストを行います。',
    userGuideDoc: 'docs/development/frontend.md',
  },
  score_rules: {
    summary:
      '【スコアルール】\nイベント種別ごとの要注目スコア加算ルールを定義・インポートします。',
    userGuideDoc: 'docs/userguide/score-rules.md',
    markerId: 'score_rules',
  },
  event_type_guides: {
    summary:
      '【イベント種別ガイド】\n運用向けの種別説明・推奨アクションを登録し、一覧や詳細に反映します。',
    userGuideDoc: 'docs/development/frontend.md',
  },
  alerts: {
    summary:
      '【アラート設定】\nメール通知ルール（イベントスコア・メトリクス閾値）の作成と有効化を行います。',
    userGuideDoc: 'docs/userguide/alerts.md',
    markerId: 'alerts',
  },
  plugins: {
    summary:
      '【プラグイン管理】\nコレクタプラグインの構成と vCenter 別の最新実行状態を確認します。\n- 管理機能が有効な場合、変更は 2 段階です。① 行を開いて有効/無効や実行間隔を変え「保存」を押す（この時点ではまだ動作は変わりません）。② 一覧右上の「変更を反映」を押すと稼働中の構成に適用されます（アプリの再起動は不要です）。\n- 管理機能が無効な場合は参照専用です。設定は TOML または環境変数で変更し、アプリを再起動して反映します。',
    userGuideDoc: 'docs/userguide/plugins.md',
    markerId: 'plugins',
  },
  diagnostics: {
    summary:
      '【診断の設定】\n診断が有効なときに管理者だけが開けます。\n- 診断用の SSH 鍵と接続先を登録し、ホスト鍵の指紋を照合して承認します。\n- vCenter または配下の ESXi と、診断用の SSH 接続先を結び付けます。\n- 追加のコマンドは製品、名前、説明、雛形、引数の種類を登録します。診断用のアカウントは強い権限を持ちます。ログ収集とは別のアカウントと鍵を使用してください。追加のコマンドが読み取り専用かどうかは本体では確かめません。',
  },
  users: {
    summary:
      '【ユーザー】\nログインできるユーザーを管理します（管理者のみ）。\n- ローカルユーザーの作成、表示名・ロール・有効状態の変更、パスワード再設定、ロック解除、ログイン解除、削除ができます。\n- ロールの変更・無効化・パスワード再設定をすると、そのユーザーのログインは解除されます。',
    userGuideDoc: 'docs/userguide/authentication.md',
  },
  directories: {
    summary:
      '【認証ディレクトリ】\nログインに使う Active Directory / LDAP を管理します（管理者のみ）。\n- 接続先・ユーザーの検索・グループの調べ方と、グループとロールの対応表を設定します。保存せずに編集中の値で接続試験ができます。\n- ログインの成否に関わる変更は、保存の前に接続試験を促します。管理者としてログインする手段を失うおそれがあるときは、新しい設定で管理者としてログインできるユーザーの資格情報を求めます。\n- 接続先・検索・グループの設定や対応表を変える、または無効にすると、そのディレクトリでログイン中のユーザーはログアウトされます。\n- 削除できるのは無効にしたディレクトリだけです（配下のユーザーも削除されます）。',
    userGuideDoc: 'docs/userguide/directory-auth.md',
  },
  chat_samples: {
    summary:
      '【チャット設定】\nチャット画面から挿入できるサンプル質問と、WEB 検索の条件（スコープ・積極度）を編集します。',
    userGuideDoc: 'docs/userguide/chat.md',
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
