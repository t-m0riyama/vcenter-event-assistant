# vCenter Event Assistant

vCenter のイベントとホスト指標（CPU/メモリ利用率など）を収集し、Web ダッシュボードで一覧・傾向を確認するツールです。

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

バックエンド:

```bash
uv run vcenter-event-assistant
# または
uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 0.0.0.0 --port 8000
```

フロント（別ターミナル）:

```bash
cd frontend && npm install && npm run dev
```

本番で API と同一プロセスから静的ファイルを配信する場合は `frontend` で `npm run build` 後、`frontend/dist` を配置すると `create_app()` が配信します。

## セキュリティ

アプリ自体は認証を行いません。本番ではリバースプロキシで TLS・認証・ネットワーク制限を行い、インターネットに直接公開しないでください。

## データベースマイグレーション（Alembic）

スキーマは起動時の `create_all` でも作成されます。明示的にマイグレーションする場合:

```bash
export DATABASE_URL=sqlite+aiosqlite:///./data/vea.db   # または PostgreSQL URL
uv run alembic upgrade head
```

新しいリビジョンの作成（モデル変更後）:

```bash
uv run alembic revision --autogenerate -m "describe_change"
```

## 開発

```bash
uv run ruff check src tests
uv run pytest -q
```

UI ドキュメント用のスクリーンショット再取得は `uv run scripts/capture_ui_screenshots.py`（詳細は [docs/development.md](docs/development.md)）。

## ドキュメント

設計・構成の整理は [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](docs/plans/2026-03-21-vcenter-event-assistant-as-built.md) を参照してください。

フロントエンドの画面例・開発コマンドは [frontend/README.md](frontend/README.md) を参照してください。

開発者向けの手順（UI スクリーンショットの再取得など）は [docs/development.md](docs/development.md) を参照してください。
