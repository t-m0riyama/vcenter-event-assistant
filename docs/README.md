# ドキュメント索引

読者別にドキュメントを分けている。まず用途に合うフォルダを開く。

`docs/plans/` と `docs/superpowers/` 内のパスは、作成当時の記録である。ファイル移動後の現行パスとは一致しないことがある。

## 利用者向け（`userguide/`）

画面操作と運用手順の正本。

| ドキュメント | 内容 |
|---|---|
| [authentication.md](userguide/authentication.md) | ログインとロール |
| [directory-auth.md](userguide/directory-auth.md) | AD / LDAP でのログイン |
| [mock-mode.md](userguide/mock-mode.md) | モックモード（デモ・開発） |
| [summary.md](userguide/summary.md) | 概要タブ |
| [events.md](userguide/events.md) | イベントタブ |
| [graph.md](userguide/graph.md) | グラフタブ |
| [digests.md](userguide/digests.md) | ダイジェスト |
| [chat.md](userguide/chat.md) | チャット |
| [alerts.md](userguide/alerts.md) | アラート |
| [score-rules.md](userguide/score-rules.md) | スコアルール |
| [plugins.md](userguide/plugins.md) | プラグイン（画面） |
| [remote-log-collector.md](userguide/remote-log-collector.md) | リモートログ収集の導入 |

## 運用向け（`operations/`）

セットアップ・本番運用・設定リファレンス。

| ドキュメント | 内容 |
|---|---|
| [getting-started.md](operations/getting-started.md) | 前提・セットアップ・起動 |
| [backend-operations.md](operations/backend-operations.md) | 監視・障害対応・アップグレード |
| [collector-plugins.md](operations/collector-plugins.md) | コレクタプラグインの設定 |
| [web-search-conditions.md](operations/web-search-conditions.md) | WEB 検索が行われる条件 |

## 開発向け（`development/`）

実装・テスト・拡張。

| ドキュメント | 内容 |
|---|---|
| [development.md](development/development.md) | マイグレーション・テスト・LLM・スクリーンショット |
| [backend.md](development/backend.md) | バックエンド全体の把握 |
| [backend-internals.md](development/backend-internals.md) | API 層の内部地図 |
| [frontend.md](development/frontend.md) | フロントエンド画面の説明 |
| [collector-plugin-authoring.md](development/collector-plugin-authoring.md) | プラグインの自作 |
| [plugin-onboarding.md](development/plugin-onboarding.md) | プラグイン共通導入仕様 |
| [llm-input-anonymization.md](development/llm-input-anonymization.md) | LLM 入力の匿名化 |
| [TODO.md](development/TODO.md) | フォローアップ・未着手一覧 |

## 機能概要（`features/`）

| ドキュメント | 内容 |
|---|---|
| [architecture.md](features/architecture.md) | システムコンテキスト・データフロー |
| [features_list.md](features/features_list.md) | 機能一覧 |
| [chat.md](features/chat.md) | チャットの概要・活用例（利用者向け正本は [userguide/chat.md](userguide/chat.md)） |

## その他

| フォルダ | 内容 |
|---|---|
| [event-type-guides/](event-type-guides/) | イベント種別ガイドの出典・優先度メモ |
| [design/](design/) | UI/UX 方針 |
| [images/](images/) | ドキュメント用スクリーンショット |
| [reports/](reports/) | 監査・アーキテクチャレビューなど時点記録 |
| [plans/](plans/) | 実装計画（時点文書） |
| [superpowers/](superpowers/) | Superpowers の設計書・実装計画（時点文書） |
| [snippets/](snippets/) | 計画書へ貼る共通方針 |
