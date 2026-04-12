# 利用開始ガイド

このドキュメントでは、vCenter Event Assistant の導入・設定・起動方法について説明します。

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


| 用途               | 例                                                                       |
| ---------------- | ----------------------------------------------------------------------- |
| PostgreSQL（本番向け） | `postgresql+asyncpg://user:pass@localhost:5432/vcenter_event_assistant` |
| SQLite ファイル      | `sqlite+aiosqlite:///./data/vea.db`（先に `mkdir -p data`）                 |
| SQLite メモリ       | `sqlite+aiosqlite:///:memory:`（主にテスト）                                   |

### ダイジェスト用 LLM（任意）

環境変数の一覧は [.env.example](.env.example) の「Batch digest」と LLM 節を参照する。

- **OpenAI 互換**（`LLM_DIGEST_PROVIDER=openai_compatible`）は、**Ollama** や **LM Studio** など、Chat Completions 形式（`POST …/chat/completions`）のローカル API にも向けられる。
- **Ollama の例:** `LLM_DIGEST_BASE_URL=http://127.0.0.1:11434/v1`、`LLM_DIGEST_MODEL` には `ollama pull` 済みのモデル名（例: `llama3.2`）。
- **`LLM_DIGEST_API_KEY` が空のときはテンプレートのみ**でダイジェストを保存し、外部 LLM は呼ばない。ローカルでキー不要なサーバでも、現状は **非空のダミー値**（例: `ollama`）を入れないと LLM 呼び出しに進まない。チャットは任意で `LLM_CHAT_*` で上書き（詳細は `.env.example`）。
- **Docker Compose で app を動かし**、ホスト上の Ollama に繋ぐ場合は、`LLM_DIGEST_BASE_URL` を `http://host.docker.internal:11434/v1` にする（`localhost` はコンテナ自身を指す。Docker Desktop の macOS / Windows を想定した例）。

## 起動

- **通常利用**: UI と API を **同一オリジン**（`http://localhost:8000`）で使う。Docker Compose、またはローカルでフロントをビルドしてからバックエンドを起動する。
- **開発用途**: バックエンド（ポート 8000）と Vite 開発サーバー（既定はポート 5173）の **二窓**。ブラウザは Vite の URL を開き、`/api` などは開発サーバーがバックエンドへプロキシする。

### 通常利用（UI をブラウザで使う）（本番ビルド済み UI）

フロントのソースを編集せず UI を使う、または本番に近い単一プロセスで試す場合。

#### Docker Compose で起動

前提: [Docker](https://docs.docker.com/get-docker/) および Docker Compose v2（`docker compose` コマンド）。

1. リポジトリルートで `.env` を用意する（未作成なら `cp .env.example .env`）。Compose は `env_file` として参照する。
2. 利用する DB に合わせて、**テンプレートのいずれかを `docker-compose.yml` にコピー**する（このファイル名が Compose の既定である）。
   - **SQLite（単一コンテナ・名前付きボリューム）:** `cp docker-compose.sqlite.yml docker-compose.yml`
   - **PostgreSQL（`postgres` サービス付き）:** `cp docker-compose.postgres.yml docker-compose.yml` のうえ、`.env` に **`POSTGRES_PASSWORD`** を設定する（`postgres` コンテナと `app` の `DATABASE_URL` の両方で同じ値が使われる）。指定例は次のとおり。
     - `.env` に 1 行追加する例: `POSTGRES_PASSWORD=changeme`
     - シェルで一時指定して起動する例: `POSTGRES_PASSWORD='your-secure-password' docker compose up --build`
     - 省略時は compose テンプレートの既定 `vea` が使われる（開発・試用向け）。
     - パスワードに `@` や `:` などが含まれる場合は、URL 用に**エンコード**した値を `POSTGRES_PASSWORD` に渡すか、シンプルな文字列に変更すること。
3. ビルドして起動する。

```bash
docker compose up --build
```

UI と API は `http://localhost:8000`（動作確認は `http://localhost:8000/health` でもよい）。

**セキュリティ:** 本アプリ単体は認証を行わない。コンテナをインターネットに直接晒さず、必要に応じてリバースプロキシ側で TLS・認証・ネットワーク制限を行うこと。

テンプレートはリポジトリで `docker-compose.sqlite.yml` / `docker-compose.postgres.yml` として管理し、コピーで生成した `docker-compose.yml` は `.gitignore` により追跡しない。

#### ローカルで Python から起動する

`frontend/dist` にビルド成果物があり `index.html` が存在するとき、FastAPI の `create_app()` が **同一プロセス**で SPA と API を配信する。`dist` が無い場合は API のみ応答し、ブラウザ用の UI は出ない。

1. リポジトリルートで `.env` を用意する（未作成なら `cp .env.example .env`）。

2. 初回または依存変更時: `frontend` で `npm install`

```bash
(cd frontend; npm install)
```

3. フロントエンドをビルドし、起動する

```bash
(cd frontend; npm run build); uv run vcenter-event-assistant
# または
(cd frontend; npm run build); uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 0.0.0.0 --port 8000

```
4. ブラウザで `http://localhost:8000` を開く。

### 開発用途（フロントエンドの改修・HMR）（Vite 開発サーバー）

React / Vite のホットリロードで UI を開発する場合は **別ターミナル**で次を実行する。

**ターミナル 1（バックエンド）**

```bash
uv run vcenter-event-assistant
# または
uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 0.0.0.0 --port 8000
```

**ターミナル 2（フロント）** — `npm install` は初回または `package.json` 更新時。

```bash
cd frontend && npm install && npm run dev
```

**ブラウザ**: 既定では `http://localhost:5173`（Vite が表示する URL でもよい）。`/api` と `/health` は開発サーバーが `http://127.0.0.1:8000` にプロキシする。フロントの npm スクリプト一覧は [docs/frontend.md](docs/frontend.md) を参照する。

## セキュリティ

アプリ自体は認証を行わない。本番ではリバースプロキシで TLS・認証・ネットワーク制限を行い、インターネットに直接公開しないこと。
