# LLM チャット（期間イベント・メトリクスコンテキスト）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: **`@superpowers:subagent-driven-development`**（推奨）または **`@superpowers:executing-plans`**。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** **`@superpowers:test-driven-development`** を厳守する。各タスクで **失敗するテストを先に書く → 実行して RED を確認（理由が「未実装」であること）→ 最小実装 → GREEN → リファクタ（緑のまま）**。**本番コードをテストより先に書かない**（探索スクリプトは捨てる）。

**Goal:** ユーザーが **指定期間**を選び、その期間の **イベント・メトリクス集約**（既存 `DigestContext` と同等）を LLM の根拠として渡し、**チャットで質問・追質問**できる。会話履歴は **クライアントが直近 N ターンを API に送付**し、サーバーは **永続化しない**（ブレインストーミング確定事項）。

**Architecture:** DB から `build_digest_context`（任意で **`vcenter_id` でスコープ**）で集約 JSON を生成し、[`digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) と同様に **OpenAI 互換（ストリーミング）**および **Gemini REST** へ送る。ダイジェスト用 `_SYSTEM_PROMPT`（「## LLM 要約」固定）は使わず、**質疑応答専用の system プロンプト**を新設。HTTP は **`POST /api/chat`**（ルーターは `prefix="/chat"`）で、Pydantic で入力検証。フロントは **新タブ + `ChatPanel`** で期間・vCenter・メッセージ UI を提供。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.0 async、httpx、pytest；React 19、TypeScript、Vite、Vitest、既存 Zod・`apiGet` パターン。

**関連 spec（任意）:** [`docs/superpowers/specs/`](../../specs/) にチャット専用 spec がある場合は本計画と整合させる。無い場合は **本ファイルを実装の単一の参照**とする。

---

## ファイル構成（変更の境界）

| ファイル | 責務 |
| -------- | ---- |
| [`src/vcenter_event_assistant/services/digest_context.py`](../../src/vcenter_event_assistant/services/digest_context.py) | `build_digest_context(..., vcenter_id: UUID \| None = None)`。`None` 時は現状どおり全 vCenter。指定時は `EventRecord` / `MetricSample` の WHERE に `vcenter_id` を追加（`vcenter_count` は該当 1 件なら 1、など仕様をテストで固定）。 |
| [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | **新規。** `run_period_chat(settings, *, context: DigestContext, messages: list[ChatMessageRow]) -> tuple[str, str \| None]`。`digest_llm` の `_trim_context_json`・httpx・OpenAI/Gemini 分岐を **流用または内部ヘルパ共有**（重複が大きければ `digest_llm` に非公開ヘルパを切り出してもよい）。**マルチターン:** `messages` をそのまま Chat Completions の `messages` に載せ、**先頭に system**、**直後に user で「集約 JSON」ブロック**（1 回だけ）を入れる設計を推奨（同一内容の重複送信を避ける）。 |
| [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py) | `ChatMessage`, `ChatRequest`, `ChatResponse`（`assistant_content: str`、`error: str \| None` 等。フィールド名は既存命名に合わせる）。 |
| [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py) | **新規。** `POST ""`（実 URL `/api/chat`）。`from`/`to`、`messages`、`vcenter_id` 任意、`top_notable_min_score` 任意。`LLM_API_KEY` 空なら **503 または 422**（ダイジェストと同様のユーザー向け文言）。 |
| [`src/vcenter_event_assistant/main.py`](../../src/vcenter_event_assistant/main.py) | `api.include_router(chat_router)`。 |
| [`tests/test_digest_context.py`](../../tests/test_digest_context.py) | `vcenter_id` フィルタの **DB 統合テスト**を追加（2 vCenter・片方だけイベント → フィルタ後件数）。 |
| [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py) | **新規。** `httpx.AsyncClient` をモックし、OpenAI 互換（および 1 本は Gemini）で **リクエスト body の messages 形**と **戻り値本文**を検証（[`test_digest_llm.py`](../../tests/test_digest_llm.py) パターン）。 |
| [`tests/test_chat_api.py`](../../tests/test_chat_api.py) | **新規。** `AsyncClient` で `POST /api/chat`、バリデーション（`from >= to`）、キー無し時のエラー。LLM は `chat_llm` をモックして **200 + assistant 文字列**を確認可能に。 |
| [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts) | リクエスト/レスポンス Zod。 |
| [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx) | **新規。** 期間入力、vCenter 選択（他パネルと同じ取得元）、メッセージ一覧、`messages` 状態、送信。 |
| [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx) | **新規。** 送信ボタン・`fetch`/`apiGet` のモック（既存パネルテストに合わせる）。 |
| [`frontend/src/App.tsx`](../../frontend/src/App.tsx) | タブ型 `Tab` に `chat` を追加、「チャット」ラベル。 |
| [`frontend/src/App.css`](../../frontend/src/App.css) | 必要最小のレイアウト（既存クラス流用で足りるなら変更なし可）。 |

**変更しないもの:** ダイジェスト生成ジョブ（`digest_run`）の挙動。**ただし** `build_digest_context` のシグネチャ拡張はダイジェスト呼び出しに **後方互換**（デフォルト `None`）で影響を限定。

**履歴上限:** サーバーで **`messages` の最大要素数または合計文字数**を切り詰め、ログに **全文は出さない**（メタのみ）。具体値は実装時に定数化（例: 20 メッセージ、または合計 32k 文字未満）。

**ストリーミング:** MVP は **非ストリーミング JSON 応答**のみ。将来 SSE 拡張する場合は別タスクとする（本計画の完了条件に含めない）。

---

## ブランチ方針

- **ベース:** `main`（作業開始前に `git pull`）。
- **ブランチ名例:** `feat/llm-chat-period-context`

---

### Task 1: `build_digest_context` の `vcenter_id` オプション（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/services/digest_context.py`](../../src/vcenter_event_assistant/services/digest_context.py)
- Modify: [`tests/test_digest_context.py`](../../tests/test_digest_context.py)

**契約:**

- `vcenter_id is None` → 現行と同じ総数・全 vCenter 対象のメトリクス集約。
- `vcenter_id` 指定 → `EventRecord.vcenter_id == vcenter_id`、および `MetricSample` も同条件。`vcenter_count` は **登録済み vCenter 総数ではなく**「対象スコープの説明用」として、**フィルタ後に意味が通る値**にする（推奨: **`1`**（単一 vCenter モードであることの明示）または **該当 vCenter が存在すれば 1**）。**テストで期待値を固定**する。

- [ ] **Step 1: 失敗するテストを書く**

  `test_digest_context.py` に `test_build_digest_context_filters_by_vcenter_id` を追加: 2 つの `VCenter` と、**異なる vcenter_id** のイベントを 1 件ずつ投入。`build_digest_context(..., vcenter_id=vid_a)` で `total_events == 1` かつそのイベントの種別が一致すること。

- [ ] **Step 2: pytest で RED を確認**

  Run: `uv run pytest tests/test_digest_context.py::test_build_digest_context_filters_by_vcenter_id -v --override-ini addopts=`

  Expected: `TypeError`（未知の引数）または `AssertionError`（件数が 2）

- [ ] **Step 3: 最小実装**

  `build_digest_context` に `vcenter_id: uuid.UUID | None = None` を追加し、全 `EventRecord` / `MetricSample` クエリに条件を付与。`vcenter_count` のセマンティクスをテスト通りに合わせる。

- [ ] **Step 4: GREEN**

  Run: `uv run pytest tests/test_digest_context.py -v --override-ini addopts=`

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/digest_context.py tests/test_digest_context.py
git commit -m "feat(digest): optional vcenter_id scope for digest context aggregation"
```

---

### Task 2: `chat_llm.run_period_chat`（TDD）

**Files:**

- Create: [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)
- Create: [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py)

**契約:**

- `settings.llm_api_key` が空 → `( "", None)` または `( "", "..." )` — **ダイジェストと同様「キー無しは LLM を呼ばない」**。呼び方は API 層で 503 にする前提で **`( "", None)` で統一**してよい（テストで固定）。
- キーあり → OpenAI 互換 POST の `messages` に **system（チャット用プロンプト）**、**集約 JSON を含む user**、続けて **クライアントからの user/assistant** が時系列で並ぶ（**最後は user**）。モックで `messages[-1]["role"] == "user"` と JSON ブロック含有を検証。
- 応答本文が空なら `digest_llm` と同様に **ValueError 系**で捕捉し、ユーザー向け文言のタプルを返すか例外に任せるかは **`digest_llm` と揃える**。

- [ ] **Step 1: 失敗するテストを書く**

  `test_chat_llm.py` に `test_run_period_chat_openai_sends_multiturn_and_returns_assistant_text` を追加。`digest_llm` と同様に `httpx.AsyncClient` をパッチし、SSE 1 行分のダミー応答を返す。**まだ `run_period_chat` が無い**ため RED。

- [ ] **Step 2: RED 確認**

  Run: `uv run pytest tests/test_chat_llm.py -v --override-ini addopts=`

- [ ] **Step 3: 最小実装**

  `run_period_chat` と `_CHAT_SYSTEM_PROMPT`（日本語・根拠は JSON のみ・推測で事実を足さない・Markdown 過剰禁止など、**ダイジェスト用プロンプトとは別ファイル定数**）。

- [ ] **Step 4: GREEN**（必要なら `test_digest_llm` と共有する定数変更が無いことを `uv run pytest tests/test_digest_llm.py -v` で確認）

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/chat_llm.py tests/test_chat_llm.py
git commit -m "feat(chat): LLM multiturn helper for period context"
```

---

### Task 3: API スキーマ + `POST /api/chat`（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py)
- Create: [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py)
- Modify: [`src/vcenter_event_assistant/main.py`](../../src/vcenter_event_assistant/main.py)
- Create: [`tests/test_chat_api.py`](../../tests/test_chat_api.py)

**契約:**

- `POST /api/chat`、body に `from`、`to`、非空 `messages`（`role` + `content`）。
- `from >= to` → **400**。
- `messages` の最終要素が `user` でない → **422**。
- `get_settings().llm_api_key` が空 → **503**（本文に「LLM が未設定」に近い日本語を含む）。

- [ ] **Step 1: 失敗するテスト**

  `test_chat_api.py` で `client.post("/api/chat", json={...})` — **ルート未登録なら 404** を期待するテストから始めてもよい（RED）。

- [ ] **Step 2: 実装**

  ルート内で `build_digest_context(session, ...)` → `run_period_chat`。`chat_llm` を `unittest.mock.patch` して統合テストでも LLM を撃たない。

- [ ] **Step 3: GREEN**

  Run: `uv run pytest tests/test_chat_api.py -v --override-ini addopts=`

  Run: `uv run pytest tests/ -v --override-ini addopts=`（または CI と同じコマンドが `docs/development.md` にあればそれ）

- [ ] **Step 4: Commit**

```bash
git add src/vcenter_event_assistant/api/schemas.py src/vcenter_event_assistant/api/routes/chat.py src/vcenter_event_assistant/main.py tests/test_chat_api.py
git commit -m "feat(api): POST /api/chat for period-scoped LLM chat"
```

---

### Task 4: フロント — スキーマ + `ChatPanel` + タブ（TDD）

**Files:**

- Modify: [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts)
- Create: [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)
- Create: [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)
- Modify: [`frontend/src/App.tsx`](../../frontend/src/App.tsx)

**契約:**

- タブ「チャット」で `ChatPanel` を表示。
- 送信で `POST /api/chat`（既存 `apiGet` / `fetch` ラッパーがあれば POST 用も踏襲）。成功時に **assistant メッセージを一覧に追加**。
- 期間未入力や `from >= to` は **送信前にバリデーション**し、エラーバナーまたはインライン表示（他パネルに合わせる）。

- [ ] **Step 1: 失敗するテスト**

  `ChatPanel.test.tsx` で「送信」クリック → `global.fetch` モックが `POST` と JSON body を受け取ることを期待。**コンポーネント未作成で RED**。

- [ ] **Step 2: 実装**

  `ChatPanel`、Zod 型、`App.tsx` のタブ追加。

- [ ] **Step 3: GREEN**

  Run: `npm test -- --run src/panels/chat/ChatPanel.test.tsx`（またはリポジトリの標準コマンド）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/schemas.ts frontend/src/panels/chat/ frontend/src/App.tsx
git commit -m "feat(ui): chat panel with period context"
```

---

### Task 5: ドキュメントと回帰

**Files:**

- Modify: [`docs/development.md`](../../docs/development.md)（存在する API 一覧・環境変数 `LLM_*` の節に **`/api/chat` とチャットの挙動**を 1 段落追加）
- Modify: [`.env.example`](../../.env.example)（チャット専用の新変数を **追加しない**。既存 `LLM_*` を流用する前提を 1 行コメントでよい）

- [ ] **Step 1:** 上記を更新。
- [ ] **Step 2:** `uv run pytest --override-ini addopts=` と `npm test -- --run`（またはプロジェクト標準）を実行しオールグリーン。
- [ ] **Step 3: Commit**

```bash
git add docs/development.md .env.example
git commit -m "docs: document LLM chat API and env"
```

---

## Plan review loop

1. 本計画と（存在すれば）[`docs/superpowers/specs/`](../../specs/) の該当 spec を **plan-document-reviewer** に渡しレビューする。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。

---

## Execution handoff

**Plan complete and saved to [`docs/superpowers/plans/2026-03-29-llm-chat-period-context.md`](./2026-03-29-llm-chat-period-context.md). Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新規サブエージェントを dispatch（**`@superpowers:subagent-driven-development`**）
2. **Inline Execution** — 同一セッションで **`@superpowers:executing-plans`** に従いチェックポイント付きで実装

**Which approach?**
