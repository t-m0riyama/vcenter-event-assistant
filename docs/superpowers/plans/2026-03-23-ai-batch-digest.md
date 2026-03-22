# AI バッチダイジェスト（B パターン）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 直近のイベント・ホスト指標を **期間集約** し、**Markdown 形式のダイジェスト** を生成して DB に保存する。オプションで **LLM** が同じ集約データから運用向けの要約文を付与する。**定期実行（日次）** と **手動トリガ API** を提供する。

**Architecture:** 集約ロジックは [`dashboard.py`](../../src/vcenter_event_assistant/api/routes/dashboard.py) の「直近 24h」クエリと同等の情報を、**任意の `[from, to)`（UTC）** に対して返す純関数／サービス層に切り出す（重複を避けるため、ダッシュボードは後続タスクでこの関数を呼ぶリファクタでもよいが、**YAGNI のため初回は digest 専用の集約モジュールに実装**し、重複は許容するか、小さな内部ヘルパーのみ共通化する）。LLM は **`httpx` のみ**（既存依存）で、**(1) OpenAI 互換の chat completions** または **(2) Google Gemini（Google AI Studio の `generateContent` REST）** のいずれかを **`llm_provider` 設定で切り替え**。**API キー未設定時はテンプレートのみ**で保存しコストゼロで検証可能にする。**Vertex AI（GCP サービスアカウント）専用エンドポイントは本プランのスコープ外**（必要なら後続タスク）。永続化は **`DigestRecord`** テーブル。バッチは **APScheduler の cron**（[`scheduler.py`](../../src/vcenter_event_assistant/jobs/scheduler.py)）に追加し、`scheduler_enabled` と別に **`digest_scheduler_enabled`** で無効化可能にする。

**Tech Stack:** FastAPI、SQLAlchemy 2 非同期、Pydantic、httpx、APScheduler cron、pytest / pytest-asyncio、Alembic（本番 PostgreSQL 向けマイグレーション）。フロントは **初回スコープ外**（API とログで十分なら UI は後続）。

---

## ファイル構成

| ファイル | 責務 |
|---------|------|
| [`src/vcenter_event_assistant/db/models.py`](../../src/vcenter_event_assistant/db/models.py) | `DigestRecord`（期間、種別、本文 Markdown、ステータス、任意で LLM メタ）。 |
| `alembic/versions/<rev>_add_digest_records.py` | 新テーブル（既存 Alembic 運用に合わせる）。 |
| `src/vcenter_event_assistant/services/digest_context.py` | `build_digest_context(session, from_utc, to_utc)` → Pydantic モデルまたは TypedDict。イベント件数、要注意件数、上位イベント（件数上限）、上位種別、高 CPU/メモリホスト（[`dashboard.py`](../../src/vcenter_event_assistant/api/routes/dashboard.py) と同様の metric_key）。 |
| `src/vcenter_event_assistant/services/digest_markdown.py` | 集約データから **LLM なし** の Markdown を生成（表・箇条書き）。 |
| `src/vcenter_event_assistant/services/digest_llm.py` | `augment_with_llm(...)` が **`settings.llm_provider`** で分岐。**OpenAI 互換:** `POST` **`settings.llm_base_url.rstrip("/") + "/chat/completions"`**（`base_url` に `/v1` を含める想定で **パスを二重に付けない**）。**Gemini:** `POST` **`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`**（`model` は `llm_model`、例: `gemini-2.0-flash`。**クエリ `key` は API キー**。公式の `x-goog-api-key` ヘッダ版でも可だが、実装は 1 本に統一）。リクエスト JSON は Gemini の **`contents` / `systemInstruction`** 形式。レスポンスは **`candidates[0].content.parts[0].text`** から本文を取得（`finishReason` / 空 candidates は失敗扱い）。**日本語**の要約セクションを返す。失敗時は例外または `None` でフォールバック。 |
| `src/vcenter_event_assistant/services/digest_run.py` | `run_digest_once(session, *, kind, from_utc, to_utc)`：集約 →（任意）LLM → `DigestRecord` 挿入。 |
| [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | `digest_scheduler_enabled`、`digest_cron`（cron 文字列 1 本）、**`llm_provider`**（`openai_compatible` \| `gemini`、既定は `openai_compatible`）、**`llm_api_key`**（OpenAI または **Google AI Studio の API キー**。空なら LLM スキップ）、**`llm_base_url`**（OpenAI 互換時のみ使用）、**`llm_model`**（両プロバイダでモデル名。Gemini 時は `gemini-2.0-flash` 等）。 |
| `src/vcenter_event_assistant/api/routes/digests.py` | `GET /api/digests`（ページング）、`GET /api/digests/{id}`、`POST /api/digests/run`（body で `from`/`to` 省略時は「昨日 0:00〜24:00 UTC」など固定ルールをドキュメント化）。 |
| [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py) | `DigestRead`、`DigestListResponse`、`DigestRunRequest`。 |
| [`src/vcenter_event_assistant/main.py`](../../src/vcenter_event_assistant/main.py) | `digests` ルータ登録。 |
| [`src/vcenter_event_assistant/jobs/scheduler.py`](../../src/vcenter_event_assistant/jobs/scheduler.py) | `cron` で日次 `run_digest`（`digest_scheduler_enabled` が真かつスケジューラ有効時のみ）。 |
| `tests/test_digest_context.py` | 集約の件数・上位件のテスト（SQLite フィクスチャ）。 |
| `tests/test_digest_run.py` | LLM 無しでレコードが 1 件入ること。 |
| `tests/test_digest_llm.py` | `MockTransport` で **OpenAI 互換 JSON**（`choices[0].message.content`）と **Gemini JSON**（`candidates[0].content.parts[0].text`）の両方をモックし、プロバイダ切替で期待パスに到達することを確認。タイムアウト時のフォールバックも共通で検証。 |
| `tests/test_digests_api.py` | `GET` / `POST` の認証挙動は既存 [`auth/dependencies.py`](../../src/vcenter_event_assistant/auth/dependencies.py) に合わせる。 |

**セキュリティ:** ダイジェスト本文に **ホスト名・VM 名** が含まれる。本番では認証必須とし、`.env.example` に LLM 送信の注意を追記する。

---

## タスク分解

### Task 1: モデルと Alembic

**Files:**
- Modify: [`src/vcenter_event_assistant/db/models.py`](../../src/vcenter_event_assistant/db/models.py)
- Create: `alembic/versions/<date>_add_digest_records.py`
- Modify: [`tests/conftest.py`](../../tests/conftest.py)（必要なら `DigestRecord` を触るテストのため）

- [ ] **Step 1: 失敗するテスト**

  `DigestRecord` に `period_start`, `period_end`（timezone-aware `DateTime`）、`kind`（`str`、例: `daily`）、`body_markdown`（`Text`）、`status`（`str`、`ok`/`error`）、`error_message`（nullable `Text`）、`llm_model`（nullable `String`）、`created_at` を持つことを ORM で定義し、マイグレーションを生成。**テスト**では `init_db` 後に `select(DigestRecord)` が空であること、または手動 insert ができること（プロジェクトの既存 DB テストパターンに合わせる）。

- [ ] **Step 2:** `uv run alembic revision --autogenerate -m "add digest records"`（モデル追加後）。SQLite の `create_all` との整合を確認。

- [ ] **Step 3:** `uv run pytest tests/ -q`（関連テストのみでも可）。

- [ ] **Step 4:** コミット `feat(db): add digest_records table`。

---

### Task 2: `digest_context` — 期間集約

**Files:**
- Create: `src/vcenter_event_assistant/services/digest_context.py`
- Create: `tests/test_digest_context.py`

- [ ] **Step 1: 失敗するテスト**

  テストデータ: 24h 内に `notable_score` の異なるイベント 2 件、`MetricSample` を `host.cpu.usage_pct` で 1 件。`build_digest_context(session, from, to)` が **イベント総数、要注意数（例: `notable_score >= 40` は dashboard と同定義に合わせる）**、上位イベント 1 件、高 CPU 1 件を含むことを assert。

- [ ] **Step 2:** `pytest tests/test_digest_context.py -v` で FAIL。

- [ ] **Step 3:** [`dashboard.py`](../../src/vcenter_event_assistant/api/routes/dashboard.py) のクエリを **`day_ago` / `now` を引数化**した形で実装。戻り値用に Pydantic モデル `DigestContext` を `schemas` か `digest_context.py` 内に定義。

- [ ] **Step 4:** `pytest tests/test_digest_context.py -v` PASS。

- [ ] **Step 5:** コミット `feat(digest): add digest context builder`。

---

### Task 3: Markdown テンプレート（LLM なし）

**Files:**
- Create: `src/vcenter_event_assistant/services/digest_markdown.py`
- Modify: `tests/test_digest_run.py`（または `test_digest_markdown.py`）

- [ ] **Step 1: 失敗するテスト**

```python
from vcenter_event_assistant.services.digest_markdown import render_template_digest

def test_render_includes_event_count():
    ctx = DigestContext(
        # ... 最小フィールド
    )
    md = render_template_digest(ctx, title="Test")
    assert "Test" in md
    assert str(ctx.total_events) in md  # フィールド名は実装に合わせる
```

- [ ] **Step 2:** 実装。見出し・表・「要注意イベント」リストは **件数上限**（例: イベント 20 件）で打ち切り、Markdown 長さに上限コメント。

- [ ] **Step 3:** pytest PASS → コミット。

---

### Task 4: `digest_run` — 永続化と LLM オプション

**Files:**
- Create: `src/vcenter_event_assistant/services/digest_run.py`
- Create: `src/vcenter_event_assistant/services/digest_llm.py`
- Modify: [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py)
- Create: `tests/test_digest_run.py`
- Create: `tests/test_digest_llm.py`

- [ ] **Step 1: 設定**

  - `llm_provider: Literal["openai_compatible", "gemini"] = "openai_compatible"`（Pydantic / `Field` で列挙）。
  - `llm_api_key: str | None = None` — **OpenAI キーと Gemini（Google AI Studio）キーの両方に使用**（プロバイダに応じて `digest_llm` が適切なエンドポイントへ送る）。
  - `llm_base_url: str = "https://api.openai.com/v1"` — **`llm_provider == openai_compatible` のときのみ**参照。
  - `llm_model: str = "gpt-4o-mini"`（例）— Gemini 利用時は `gemini-2.0-flash` 等に変更する想定を `description` に記載。
  - `Field` の `description` に「**`llm_api_key` 空ならテンプレートのみ**」「Gemini は [Google AI Studio](https://aistudio.google.com/) でキー取得」旨。

- [ ] **Step 2: LLM ユニットテスト**

  - **OpenAI 互換:** `httpx` モックで 200 JSON（`choices[0].message.content`）を返し、`augment_with_llm` が追記テキストを返すこと。
  - **Gemini:** 同様に `generativelanguage.googleapis.com` 向け URL にマッチするレスポンスで 200 JSON（`candidates[0].content.parts[0].text`）を返し、同関数が本文を取り出すこと。
  - `llm_api_key` なしで **HTTP を呼ばない**（テンプレートのみのパス）。

- [ ] **Step 3: `run_digest_once`**

  トランザクション内: `build_digest_context` → `render_template_digest` →（キーありなら LLM マージ）。

  **LLM 失敗時の方針（固定）:** 集約・テンプレート生成まで成功していれば **`status=ok`** のまま `body_markdown` にテンプレート本文を保存する。LLM がタイムアウト／4xx／5xx のときは **`error_message`**（または本文末尾の短い注記）に「LLM 要約は省略」と記録し、必要なら **`llm_model` は null**。**集約や DB 書き込み自体が失敗**した場合のみ `status=error` とする。

- [ ] **Step 4:** `tests/test_digest_run.py` で DB に 1 行 insert を確認。

- [ ] **Step 5:** コミット。

---

### Task 5: REST API

**Files:**
- Create: `src/vcenter_event_assistant/api/routes/digests.py`
- Modify: [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py)
- Modify: [`src/vcenter_event_assistant/main.py`](../../src/vcenter_event_assistant/main.py)
- Create: `tests/test_digests_api.py`

- [ ] **Step 1: 失敗するテスト**

  `GET /api/digests` が `200` と `items` 配列。`POST /api/digests/run` で body 省略時に「昨日 UTC」のウィンドウで `run_digest_once` が動く（モックするなら dependency override）。

- [ ] **Step 2:** ルータ実装。`DigestRead` に `id`, `period_start`, `period_end`, `kind`, `body_markdown`, `status`, `error_message`（nullable）, `llm_model`（nullable）, `created_at`。`GET /api/digests` は `limit`（既定 50、上限 200）, `offset`（既定 0）を `Query` で受け、総件数は `total` を返す（既存イベント一覧と同パターンでよい）。

- [ ] **Step 3:** `uv run pytest tests/test_digests_api.py -v` PASS。

- [ ] **Step 4:** コミット。

---

### Task 6: APScheduler 日次ジョブ

**Files:**
- Modify: [`src/vcenter_event_assistant/jobs/scheduler.py`](../../src/vcenter_event_assistant/jobs/scheduler.py)
- Modify: [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py)

- [ ] **Step 1:** `digest_scheduler_enabled: bool = False`。`digest_cron: str = "0 7 * * *"`（**例**: 毎日 UTC 7:00 — コメントで変更可と明記）。

- [ ] **Step 2:** `scheduler.add_job(run_daily_digest_utc_yesterday, "cron", ...)` を `digest_scheduler_enabled` が True のときだけ追加。ジョブ内は **`session_scope` + `run_digest_once`**。

- [ ] **Step 3:** スケジューラを直接テストしにくい場合は、`run_daily_digest_utc_yesterday` を別モジュールの **純関数**として単体テスト（日付境界のみ）。

- [ ] **Step 4:** コミット。

---

### Task 7: ドキュメントと `.env.example`

**Files:**
- Modify: [`.env.example`](../../.env.example)
- Modify: [`README.md`](../../README.md) または [`docs/development.md`](../../docs/development.md) に短い節を追加（**日本語**）

- [ ] **Step 1:** `DIGEST_SCHEDULER_ENABLED`、**`LLM_PROVIDER`（`openai_compatible` / `gemini`）**、`LLM_API_KEY`、`LLM_BASE_URL`（OpenAI 互換時）、`LLM_MODEL` の説明。Gemini 利用時は **Google AI Studio のキー**を `LLM_API_KEY` に設定すること。個人情報・ホスト名が **選択したプロバイダの API** に送られる旨。

- [ ] **Step 2:** コミット `docs: document digest and llm env`。

---

## 実行引き渡し

実装完了後は @superpowers:verification-before-completion に従い、`uv run ruff check src tests`、`uv run pytest -q` を実行してから完了宣言する。

**Plan review:** 2026-03-23 に `plan-document-reviewer` 観点でレビュー済み（記録は下記「Plan Review 記録」）。

**実行オプション:** 本計画を保存したうえで、(1) **サブエージェント駆動**（推奨）— @superpowers:subagent-driven-development、(2) **インライン実行** — @superpowers:executing-plans。どちらで進めるか指定してください。

---

## Plan Review 記録

**参照 Spec:** 本機能の単独 spec はなし（Goal / Architecture は本書冒頭）。

**Status:** Approved（以下の指摘を本文に反映済み）

**Issues（修正前にあったもの）:**

- Task 4: LLM 失敗時の `status` / `error_message` の振る舞いが二択のまま残っており、実装者が迷う → **「テンプレ成功なら `ok`、LLM 失敗は注記のみ」** に固定して Task 4 に明記した。
- Task 5: `DigestRead` のフィールドが `DigestRecord` より少なく、API が不完全になる → **`error_message` / `llm_model` とページング Query** を Step 2 に追記した。
- ファイル構成表: `respx` は `pyproject.toml` に未記載 → **`MockTransport` 優先、respx は任意で dev 追加** と明記した。
- `digest_llm.py`: `llm_base_url` とパス結合で `/v1` が二重になりうる → **URL 結合ルール**をファイル表に追記した。

**Recommendations（ブロックしない）:**

- 同一 `[from,to)` で `POST` を複数回すると行が重複する仕様でよいかは運用で確認（冪等キーは後続でも可）。
- Task 6 の cron は APScheduler の `CronTrigger` 利用を実装時にコードコメントで明示するとよい。

**追記（2026-03-23）:** LLM を **Google Gemini（Google AI Studio / `generateContent` REST）** にも対応する方針を反映。Vertex AI 専用はスコープ外。

---

## 後続（本プランの範囲外）

- 概要タブ／専用画面で **最新ダイジェストを表示**（React）。
- `dashboard_summary` と `digest_context` の **クエリ共通化**による DRY 化。
- 週次 `kind=weekly` と cron 追加。
