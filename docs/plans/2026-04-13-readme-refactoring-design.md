# README.md の整理とドキュメント分割（デザイン）

`README.md` が長大化しているため、内容を整理し、セットアップ方法や開発者向けの詳細な操作手順を `docs/` 配下の別ファイルに分割します。

## 変更の目的
- `README.md` をプロジェクトの概要、主な機能、制約事項を素早く把握できる軽量なものにする。
- ユーザーの目的（使い始める、開発に貢献するなど）に合わせて参照すべきドキュメントを明確にする。

## 新規・更新ファイル構成

### [NEW] [docs/getting-started.md](file:///Users/moriyama/git/vcenter-event-assistant/docs/getting-started.md)
以下の「利用開始に向けた情報」を `README.md` から移動して集約します。
- 前提（Python バージョン、uv 等）
- セットアップ（`.env` 作成、データベース URL、LLM 設定等）
- 起動方法（Docker Compose、ローカル Python 実行、開発用 Vite 実行）
- セキュリティ上の注意点

### [MODIFY] [docs/development.md](file:///Users/moriyama/git/vcenter-event-assistant/docs/development.md)
「開発者向けの操作手順」を `README.md` から移動し、既存の内容の前に配置します。
- データベースマイグレーション（Alembic）
- 開発時コマンド（Ruff, Pytest 等）
- ※既存の「UI スクリーンショット」や「API 仕様」などはその後に続く形にします。

### [MODIFY] [README.md](file:///Users/moriyama/git/vcenter-event-assistant/README.md)
以下の章のみを保持し、その他の詳細情報は新規作成したドキュメントへのリンクに置き換えます。
- ## 主なユースケース
- ## アーキテクチャ（Mermaid 図を含む）
- ## 特長
- ## 制約、その他
- ## 商標および免責
- ## ドキュメント（リンク集を更新）
- ## ライセンス

## 移行マップ

| README.md のセクション | 移行先 |
| :--- | :--- |
| ## 前提 | `docs/getting-started.md` |
| ## セットアップ | `docs/getting-started.md` |
| ## 起動 | `docs/getting-started.md` |
| ## セキュリティ | `docs/getting-started.md` |
| ## データベースマイグレーション | `docs/development.md` (先頭) |
| ## 開発 | `docs/development.md` (先頭) |
| ## ドキュメント | `README.md` (更新) |

## 検証方法
- すべてのリンクが正しく機能することを確認する。
- 分割後の `docs/getting-started.md` の手順に従って環境構築・起動が可能であることを（机上で）再確認する。
