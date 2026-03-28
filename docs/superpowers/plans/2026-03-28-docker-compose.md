# Docker Compose コンテナ実行 実装計画

> **For agentic workers:** 本計画の実装は **`@superpowers:subagent-driven-development`**（タスク単位のサブエージェント + 二段レビュー）を既定とする。代替は `superpowers:executing-plans`。チェックボックス（`- [ ]`）で進捗を追う。
>
> **TDD について:** アプリの Python ロジックは変更しない。**Dockerfile / Compose はユニットテストの対象外**とし、各タスクの検証は **`docker compose build`** および **`curl` / ブラウザでの `/health` と UI** で行う（インフラ定義のため `@superpowers:test-driven-development` は適用しない）。

**Goal:** リポジトリに **multi-stage Dockerfile** と **Compose テンプレート 2 種**（`docker-compose.sqlite.yml` / `docker-compose.postgres.yml`）を追加し、利用者が **いずれかを `docker-compose.yml` にコピー**してから `docker compose up --build` できるようにする。README に手順を追記し、生成された `docker-compose.yml` は **`.gitignore` で追跡しない**。

**Architecture:** ビルド Stage 1 で [frontend/](frontend) を `npm ci` → `npm run build` し、`frontend/dist` を成果物とする。Stage 2 で `python:3.12-slim` に **uv** を導入し、`pyproject.toml` / `uv.lock` / [src/](src) を同期（`--frozen --no-dev`）。ランタイムの作業ディレクトリはリポジトリルート相当とし、[src/vcenter_event_assistant/main.py](src/vcenter_event_assistant/main.py) の `FRONTEND_DIST`（`.../frontend/dist`）が解決できるようにする。Compose は **SQLite 用**（`app` + 名前付きボリューム `/data`）と **PostgreSQL 用**（`postgres` + `app`、`depends_on` + healthcheck）を **それぞれ単独で完結**した YAML とし、**`-f` マージは使わない**。

**Tech Stack:** Docker / Docker Compose v2、Node（frontend ビルド）、Python 3.12、uv、`npm ci`（[frontend/package-lock.json](frontend/package-lock.json) 利用）、PostgreSQL 16（公式イメージ）。

**参照:** 設計の経緯は Cursor 計画 `.cursor/plans/docker_compose_対応_a1efda04.plan.md`（ユーザー反復で「テンプレートを `docker-compose.yml` にコピー」方式に確定）。

---

## ファイル構成

| ファイル | 責務 |
|----------|------|
| [Dockerfile](Dockerfile)（新規・リポジトリルート） | multi-stage: frontend ビルド → Python/uv でパッケージ同期、`vcenter-event-assistant` 起動 |
| [.dockerignore](.dockerignore)（新規） | ビルドコンテキストから `node_modules`、`.git`、`.venv` 等を除外 |
| [docker-compose.sqlite.yml](docker-compose.sqlite.yml)（新規） | `app` のみ、`DATABASE_URL` は SQLite 絶対パス、`vea_data` → `/data` |
| [docker-compose.postgres.yml](docker-compose.postgres.yml)（新規） | `postgres` + `app`、healthcheck、`DATABASE_URL` は `postgres` ホスト名 |
| [.gitignore](.gitignore)（修正） | `docker-compose.yml` を追加（コピー生成物をコミットしない） |
| [README.md](README.md)（修正） | 「Docker Compose で起動」: `cp` 手順、`docker compose up --build`、セキュリティ注意 |

**変更しないもの:** [src/vcenter_event_assistant/__init__.py](src/vcenter_event_assistant/__init__.py)（既に `0.0.0.0:8000`）、アプリ設定ロジック（`.env` は `env_file` で引き続き注入）。

---

## コンテナ内の前提（実装で固定すること）

- **SQLite の `DATABASE_URL`:** `sqlite+aiosqlite:////data/vea.db`（先頭 4 スラッシュでコンテナ内絶対パス `/data/vea.db`）。
- **ポート:** ホスト `8000` → コンテナ `8000`（[__init__.py](src/vcenter_event_assistant/__init__.py) の既定と一致）。
- **PostgreSQL の接続文字列:** 例 `postgresql+asyncpg://vea:パスワード@postgres:5432/vcenter_event_assistant`。パスワードに `@` 等が含まれる場合は **URL エンコード**が必要であることを README に明記する。

---

### Task 1: `.dockerignore`

**Files:**
- Create: [.dockerignore](.dockerignore)

- [ ] **Step 1:** 次を含む `.dockerignore` を追加する（ビルドに不要なものを除外）。

```
.git
.gitignore
.venv
venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
htmlcov
frontend/node_modules
frontend/dist
frontend/playwright-report
frontend/test-results
data
*.db
.env
.cursor
.worktrees
docs
tests
```

- [ ] **Step 2:** `docker build` のコンテキストが軽くなっていることを確認（Task 4 で初めて実 build してもよい）。

- [ ] **Step 3:** Commit

```bash
git add .dockerignore
git commit -m "chore(docker): add .dockerignore for build context"
```

---

### Task 2: `Dockerfile`（multi-stage）

**Files:**
- Create: [Dockerfile](Dockerfile)

- [ ] **Step 1:** 次の方針で `Dockerfile` を書く（バージョンは固定タグを推奨: `node:22-bookworm-slim`、`python:3.12-slim-bookworm` 等）。

  - **Stage `frontend`:** `WORKDIR /app/frontend`、`COPY frontend/package.json frontend/package-lock.json`、`RUN npm ci`、`COPY frontend/`、`RUN npm run build`。
  - **Stage `runtime`:** ベース `python:3.12-slim-bookworm`。公式手順に従い **uv** をインストール（例: `COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` または install script — 実装時点の uv 推奨手順に合わせる）。
  - `WORKDIR /app`
  - `COPY pyproject.toml uv.lock README.md ./`（`uv.lock` 必須）
  - `COPY src ./src`
  - `COPY --from=frontend /app/frontend/dist ./frontend/dist`
  - `RUN uv sync --frozen --no-dev`
  - 非 root ユーザー（例: `useradd -m appuser`）を作成し、`chown -R appuser:appuser /app` のうえ `USER appuser`
  - `ENV PATH="/app/.venv/bin:$PATH"`
  - `EXPOSE 8000`
  - `CMD ["vcenter-event-assistant"]`（[pyproject.toml](pyproject.toml) の `[project.scripts]` が生成するエントリポイントを `PATH` 上で実行できること）

- [ ] **Step 2:** ローカルでビルド検証。

```bash
cd /Users/moriyama/git/vcenter-event-assistant
docker build -t vea:test .
```

期待: エラーなく完了し、イメージ `vea:test` が存在する。

- [ ] **Step 3:** 対話なしでヘルスチェック（コンテナ起動）。

```bash
docker run --rm -e DATABASE_URL=sqlite+aiosqlite:////tmp/vea.db -p 8000:8000 vea:test
# 別ターミナル
curl -sf http://127.0.0.1:8000/health
```

期待: HTTP 200 相当（本文は既存 `/health` の JSON）。

- [ ] **Step 4:** Commit

```bash
git add Dockerfile
git commit -m "feat(docker): add multi-stage Dockerfile for app and frontend dist"
```

---

### Task 3: `docker-compose.sqlite.yml`

**Files:**
- Create: [docker-compose.sqlite.yml](docker-compose.sqlite.yml)

- [ ] **Step 1:** 次の内容に相当する Compose を追加する（インデントは YAML 2 スペース）。

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: sqlite+aiosqlite:////data/vea.db
    volumes:
      - vea_data:/data

volumes:
  vea_data:
```

- [ ] **Step 2:** 検証（まだ `docker-compose.yml` は作らない）。`-f` で直接指定。

```bash
cp .env.example .env   # 未作成なら
docker compose -f docker-compose.sqlite.yml up --build -d
curl -sf http://127.0.0.1:8000/health
docker compose -f docker-compose.sqlite.yml down
```

期待: `up` が成功し、`/health` が応答する。

- [ ] **Step 3:** Commit

```bash
git add docker-compose.sqlite.yml
git commit -m "feat(docker): add sqlite compose template"
```

---

### Task 4: `docker-compose.postgres.yml`

**Files:**
- Create: [docker-compose.postgres.yml](docker-compose.postgres.yml)

- [ ] **Step 1:** 自己完結型の Compose を追加する（例: ユーザー `vea`、DB 名 `vcenter_event_assistant`、パスワードは `${POSTGRES_PASSWORD:-vea}` でデフォルト可）。

  - `postgres` サービス: イメージ `postgres:16-alpine`（または `16-bookworm`）、`healthcheck` に `pg_isready`。
  - `app` サービス: `depends_on: postgres: condition: service_healthy`。
  - `app.environment.DATABASE_URL` は `postgresql+asyncpg://vea:...@postgres:5432/vcenter_event_assistant`。**パスワード部分**は compose の変数と一致させる（同一の `POSTGRES_PASSWORD` を `postgres` と `app` で共有）。

- [ ] **Step 2:** 検証。

```bash
docker compose -f docker-compose.postgres.yml up --build -d
curl -sf http://127.0.0.1:8000/health
docker compose -f docker-compose.postgres.yml down -v
```

期待: `postgres` が healthy になった後に `app` が起動し、`/health` が応答する。

- [ ] **Step 3:** Commit

```bash
git add docker-compose.postgres.yml
git commit -m "feat(docker): add postgres compose template"
```

---

### Task 5: `.gitignore` に `docker-compose.yml`

**Files:**
- Modify: [.gitignore](.gitignore)

- [ ] **Step 1:** 既存の「docker compose override」付近に次を追加する。

```
# テンプレートからコピーしたローカル用（テンプレートは追跡する）
docker-compose.yml
```

- [ ] **Step 2:** Commit

```bash
git add .gitignore
git commit -m "chore(docker): ignore generated docker-compose.yml"
```

---

### Task 6: README に「Docker Compose で起動」

**Files:**
- Modify: [README.md](README.md)

- [ ] **Step 1:** [起動](README.md) セクションの近く（本番静的配信の説明の後など）に **日本語**で次を満たす節を追加する。

  - 前提: Docker / Docker Compose v2。
  - **SQLite 利用時:** `cp docker-compose.sqlite.yml docker-compose.yml` → `docker compose up --build`（初回は `--build` 推奨）。
  - **PostgreSQL 利用時:** `cp docker-compose.postgres.yml docker-compose.yml` → `.env` で `POSTGRES_PASSWORD` 等を設定 → `docker compose up --build`。
  - アクセス: `http://localhost:8000`（`/health` で確認可能）。
  - **セキュリティ:** 既存の「アプリ単体は認証しない」に倣い、コンテナ直公開の注意を 1 文。
  - **パスワードの URL エンコード**（PostgreSQL URL に特殊文字がある場合）。

- [ ] **Step 2:** 誤字・リンクを確認。

- [ ] **Step 3:** Commit

```bash
git add README.md
git commit -m "docs: add Docker Compose run instructions"
```

---

### Task 7: 最終確認（コピー手順どおり）

- [ ] **Step 1:** SQLite テンプレートのコピー動線。

```bash
cp docker-compose.sqlite.yml docker-compose.yml
docker compose up --build -d
curl -sf http://127.0.0.1:8000/health
docker compose down
rm docker-compose.yml
```

- [ ] **Step 2:** PostgreSQL テンプレートのコピー動線（`.env` にパスワードを設定したうえで）。

```bash
cp docker-compose.postgres.yml docker-compose.yml
docker compose up --build -d
curl -sf http://127.0.0.1:8000/health
docker compose down -v
rm docker-compose.yml
```

- [ ] **Step 3:** `git status` で `docker-compose.yml` が無視されていることを確認。

---

## 計画レビュー（任意・スキル手順）

1. 本ファイルのパスと、参照設計（`.cursor/plans/docker_compose_対応_a1efda04.plan.md`）をコンテキストに **`plan-document-reviewer` サブエージェント**へ渡しレビューする。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。

---

## 実行の進め方（完了後）

計画ファイルは `docs/superpowers/plans/2026-03-28-docker-compose.md` に保存済み。**実装の進め方は次のいずれかを選ぶ。**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。**必須サブスキル:** `@superpowers:subagent-driven-development`
2. **Inline Execution** — 同一セッションで `@superpowers:executing-plans` に従いチェックポイント付きで一括実行する。

どちらで進めるか指定がなければ **1** を推奨する。
