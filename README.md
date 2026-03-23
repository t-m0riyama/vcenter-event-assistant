# vCenter Event Assistant

vCenter のイベントとホスト指標（CPU/メモリ利用率など）を収集し、Web ダッシュボードで一覧・傾向を確認するツールです。期間を指定した **Markdown ダイジェスト**の生成や、環境設定に応じた **LLM による補助（ベータ）**にも対応します。

## 主なユースケース

- vCenter の **イベント**を蓄積し、時系列で一覧・フィルタし、ルールに基づく **注目度（スコア）** で優先度付けして確認できます。
- ESXi ホストの **CPU/メモリ利用率**（`quickStats` 由来）を定期サンプルし、**推移・ダッシュボード**で傾向を確認できます。
- **複数 vCenter** を登録し、手動またはスケジュールされた **収集ジョブ**でデータを取り込めます。
- （任意）期間を指定して **Markdown ダイジェスト**を生成できます。環境設定により **LLM で要約・整形**できます（運用レポートの下書き用途）。**LLM によるダイジェスト補助はベータ版**であり、挙動・出力品質・設定は予告なく変わり得ます。

## 特長

- **オープンソース**（[Apache License 2.0](LICENSE)）であり、**自前ホスト**が可能です。
- DB は **PostgreSQL / SQLite** を `DATABASE_URL` で選択できます（[前提](#前提)）。
- 収集は **pyVmomi** 経由です。バックエンドは **FastAPI**、フロントは **React** のダッシュボード UI です。
- 収集間隔・データ保持日数・ダイジェストのスケジュールなどを **環境変数で調整**できます（[.env.example](.env.example) および `Settings`）。

## 不得意・制約

- **本アプリ単体では認証を行いません。本番ではリバースプロキシ等で TLS・認証・ネットワーク制限を行ってください**（詳細は [セキュリティ](#セキュリティ)）。
- **Broadcom / VMware の公式製品ではありません**（[商標および免責](#商標および免責)）。
- ホスト指標は **`quickStats` ベースの限定的な項目**であり、vCenter の全パフォーマンスカウンタ網羅や VM 単位の詳細キャパシティプランニング専用ツールではありません。
- **フル SIEM やコンプライアンス監査の唯一の証跡ソース**としての置き換えは想定しません（保持・改ざん耐性・長期アーカイブは運用設計が別途必要です）。
- **LLM 利用時（ベータ）**は外部 API への送信・コスト・レイテンシ・プロンプトに載るデータ範囲に注意してください。ベータ機能のため、本番の唯一の根拠資料にしない運用を推奨します。

## 商標および免責

本プロジェクトは Broadcom Inc. およびその関連会社の公式製品・サービスではありません。VMware、vCenter などの名称は各社の商標であり、本プロジェクトはそれらの権利者と提携・承認・後援関係にありません。

## 前提

- Python 3.12+
- 依存管理: [uv](https://github.com/astral-sh/uv)

## セットアップ

```bash
uv sync --all-groups
cp .env.example .env
# .env の DATABASE_URL を編集（下記）
```

### データベース URL（`DATABASE_URL`）

| 用途 | 例 |
|------|-----|
| PostgreSQL（本番向け） | `postgresql+asyncpg://user:pass@localhost:5432/vcenter_event_assistant` |
| SQLite ファイル | `sqlite+aiosqlite:///./data/vea.db`（先に `mkdir -p data`） |
| SQLite メモリ | `sqlite+aiosqlite:///:memory:`（主にテスト） |

## 起動

バックエンドは、次のとおりです。

```bash
uv run vcenter-event-assistant
# または
uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 0.0.0.0 --port 8000
```

フロント（別ターミナル）は、次のとおりです。

```bash
cd frontend && npm install && npm run dev
```

本番で API と同一プロセスから静的ファイルを配信する場合は、`frontend` で `npm run build` したあと `frontend/dist` を配置すると、`create_app()` が配信します。

## セキュリティ

アプリ自体は認証を行いません。本番ではリバースプロキシで TLS・認証・ネットワーク制限を行い、インターネットに直接公開しないでください。

## データベースマイグレーション（Alembic）

スキーマは起動時の `create_all` でも作成されます。明示的にマイグレーションする場合は、次を実行します。

```bash
export DATABASE_URL=sqlite+aiosqlite:///./data/vea.db   # または PostgreSQL URL
uv run alembic upgrade head
```

新しいリビジョンを作成する場合（モデル変更後）は、次を実行します。

```bash
uv run alembic revision --autogenerate -m "describe_change"
```

## 開発

```bash
uv run ruff check src tests
uv run pytest -q
```

UI ドキュメント用のスクリーンショットの再取得は、`uv run scripts/capture_ui_screenshots.py` を実行します（詳細は [docs/development.md](docs/development.md)）。

## ドキュメント

設計・構成の整理は [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](docs/plans/2026-03-21-vcenter-event-assistant-as-built.md) を参照してください。

フロントエンドの画面例・開発コマンドは [frontend/README.md](frontend/README.md) を参照してください。

開発者向けの手順（UI スクリーンショットの再取得など）は [docs/development.md](docs/development.md) を参照してください。

## ライセンス

本リポジトリは [Apache License 2.0](LICENSE) の下で提供されます。著作権表示は [NOTICE](NOTICE) を参照してください。
