# vCenter Event Assistant

vCenter のイベントとホスト指標（CPU/メモリ利用率など）を収集し、Web ダッシュボードで一覧・傾向を確認するツールである。期間を指定した **Markdown ダイジェスト**の生成や、環境設定に応じた **LLM による補助（ベータ）**にも対応する。

## 主なユースケース

- vCenter の **イベント**を蓄積し、時系列で一覧・フィルタし、ルールに基づく **注目度（スコア）** で優先度付けして確認できる。
- ESXi ホストの **CPU/メモリ利用率**（`quickStats` 由来）を定期サンプルし、**推移・ダッシュボード**で傾向を確認できる。
- **複数 vCenter** を登録し、手動またはスケジュールされた **収集ジョブ**でデータを取り込める。
- 障害などの発生時、イベント（発生件数）とESXiホストの負荷情報の推移を1つのグラフに視覚化できる。
- 期間を指定して、イベントとESXiホストの負荷情報のダイジェストを生成できる。環境設定により **LLM で要約・整形**できる。※**LLM によるダイジェスト補助はベータ版**であり、挙動・出力品質・設定は予告なく変わり得る。

フロントエンドの画面例などは [docs/frontend.md](docs/frontend.md) を参照する。

## アーキテクチャ

- **バックエンド**: **FastAPI** が `/api`・永続化・**pyVmomi** による vCenter 収集・**APScheduler** などを担う。DB は **`DATABASE_URL`** で **PostgreSQL** または **SQLite** を選択する。
- **フロントエンド**: **React**（SPA）がダッシュボード等の UI を提供し、バックエンドの `/api` を呼び出す。開発時は Vite が `/api` をプロキシする。

**データフローやバックエンド／フロントの詳細**は [docs/architecture.md](docs/architecture.md) を参照する。

```mermaid
flowchart TB
  Browser[ブラウザ]
  Proxy[リバースプロキシ（任意）]
  subgraph fe [フロントエンド]
    FE[React_SPA]
  end
  subgraph be [バックエンド]
    BE[FastAPI]
    Sched[APScheduler]
  end
  VC[vCenter]
  LLM[LLM_API（任意、ベータ）]

  Browser --> Proxy
  Proxy --> FE
  FE -->|HTTP_API| BE
  Sched -->|定期実行で収集| VC
  BE -->|API操作や手動収集| VC
  BE -.->|ダイジェスト要約| LLM
```

## 特長

- **オープンソース**（[Apache License 2.0](LICENSE)）であり、セルフ**ホスト**での動作が可能である。
- DB は **PostgreSQL / SQLite** を `DATABASE_URL` で選択できる（[前提](#前提)）。
- 実績の多いオープンソースエコシステムを採用（収集は **pyVmomi** 、バックエンドは **FastAPI**、フロントは **React** ）
- 収集間隔・データ保持日数・ダイジェストのスケジュールなどを **環境変数で調整**できる（[.env.example](.env.example) 参照）。
- イベントの種別に応じて、一般的な意味・原因・対象要/不要・対処方法・のガイドを設定できる。（主要イベント(400超)について、イベント種別ガイドを同梱）
- イベントの種別ごとに、スコアをカスタマイズすることができ、環境に応じた重要度の高いイベントを見落とさないための仕組みを提供する。

## 制約、その他

- **本アプリ単体では認証を行わない。本番ではリバースプロキシ等で TLS・認証・ネットワーク制限を行うこと**（詳細は [セキュリティ](#セキュリティ)）。
- **Broadcom / VMware の公式製品ではない**（[商標および免責](#商標および免責)）。
- ホスト指標は `**quickStats` ベースの限定的な項目**であり、vCenter の全パフォーマンスカウンタ網羅や VM 単位の詳細キャパシティプランニング専用ツールではない。
- **フル SIEM やコンプライアンス監査の唯一の証跡ソース**としての置き換えは想定しない（保持・改ざん耐性・長期アーカイブは運用設計が別途必要である）。
- **LLM 利用時（ベータ）**は外部 API への送信・コスト・レイテンシ・プロンプトに載るデータ範囲に注意すること。ベータ機能のため、本番の唯一の根拠資料にしない運用を推奨する。

## 商標および免責

本プロジェクトは Broadcom Inc. およびその関連会社の公式製品・サービスではない。VMware、vCenter などの名称は各社の商標であり、本プロジェクトはそれらの権利者と提携・承認・後援関係にない。

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

1. 初回または依存変更時: `frontend` で `npm install`

```bash
cd frontend
npm install
```

2. `frontend` で `npm run build`（`frontend/dist` を生成）

```bash
npm run build
```

3. リポジトリルートでバックエンドを起動する。

```bash
cd ../

uv run vcenter-event-assistant
# または
uv run uvicorn vcenter_event_assistant.main:create_app --factory --host 0.0.0.0 --port 8000
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

## データベースマイグレーション（Alembic）

スキーマは起動時の `create_all` でも作成される。明示的にマイグレーションする場合は次を実行する。

```bash
export DATABASE_URL=sqlite+aiosqlite:///./data/vea.db   # または PostgreSQL URL
uv run alembic upgrade head
```

新しいリビジョンを作成する場合（モデル変更後）は次を実行する。

```bash
uv run alembic revision --autogenerate -m "describe_change"
```

## 開発

```bash
uv run ruff check src tests
uv run pytest -q
```

UI ドキュメント用のスクリーンショットの再取得は、**起動済みのインスタンス**（既定 `http://127.0.0.1:8000`）に向けて `uv run scripts/capture_ui_screenshots.py` を実行する（詳細は [docs/development.md](docs/development.md)）。一方、**Playwright E2E**（`frontend` で `npm run e2e`）は **テスト専用プロセスを新規起動**して実施する（既定は別ポート `9323`）。

## ドキュメント

- **アーキテクチャ**（システムコンテキスト・データフロー）: [docs/architecture.md](docs/architecture.md)
- **設計・モジュール対応・改善タスク**（現状実装ベース）: [docs/plans/2026-03-21-vcenter-event-assistant-as-built.md](docs/plans/2026-03-21-vcenter-event-assistant-as-built.md)
- **開発者向け手順**（UI スクリーンショットの再取得など）: [docs/development.md](docs/development.md)

## ライセンス

本リポジトリは [Apache License 2.0](LICENSE) の下で提供される。著作権表示は [NOTICE](NOTICE) を参照する。