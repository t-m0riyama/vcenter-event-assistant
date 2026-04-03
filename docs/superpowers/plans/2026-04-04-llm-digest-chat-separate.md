# LLM_DIGEST_* / LLM_CHAT_* 分離 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ダイジェストは `LLM_DIGEST_*` のみ、チャットは `LLM_CHAT_*` で任意上書きし、未指定フィールドは `LLM_DIGEST_*` にフォールバックする。旧 `LLM_*` は**読み込まない**（破壊的変更）。`build_chat_model` は `purpose: "digest" | "chat"` で実効プロファイルを解決する。

**Architecture:** `Settings` に `llm_digest_*` と任意の `llm_chat_*` を持たせる。純関数 `resolve_llm_profile(settings, purpose)`（新規 [`src/vcenter_event_assistant/services/llm_profile.py`](../../src/vcenter_event_assistant/services/llm_profile.py)）がフィールド単位マージを返す。[`llm_factory.build_chat_model`](../../src/vcenter_event_assistant/services/llm_factory.py) は解決済みプロファイルで `ChatOpenAI` / `ChatGoogleGenerativeAI` を生成。[`llm_tracing.build_llm_runnable_config`](../../src/vcenter_event_assistant/services/llm_tracing.py) は呼び出し種別に応じた実効 `provider` / `model` を metadata に載せる。チャット API の 503 は「実効チャット API キーが空」のとき。

**Tech Stack:** Python 3.12+、Pydantic Settings、LangChain（`langchain_openai` / `langchain_google_genai`）、pytest、既存の `Settings` / `get_settings()`（`lru_cache`）パターン。

**実装順序（TDD との整合）:** 先に **Task 1（Settings）** で `llm_digest_*` / `llm_chat_*` を定義する。続けて **Task 2（`llm_profile`）** で RED→GREEN。以降 Task 3→5。隔離した作業用に **git worktree** を使う場合は Cursor スキル `using-git-worktrees` を参照。

---

## 変更ファイル一覧（責務）

| ファイル | 役割 |
|----------|------|
| [`src/vcenter_event_assistant/services/llm_profile.py`](../../src/vcenter_event_assistant/services/llm_profile.py)（新規） | `ResolvedLlmProfile`、`resolve_llm_profile`、`effective_chat_api_key`（実効キー文字列） |
| [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | `llm_*` → `llm_digest_*` リネーム、`llm_chat_*` 追加、JSDoc/Field description 更新 |
| [`src/vcenter_event_assistant/services/llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py) | `build_chat_model(settings, purpose=..., config=...)` |
| [`src/vcenter_event_assistant/services/digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) | 実効ダイジェストキー・ログ・`build_chat_model(..., purpose="digest")` |
| [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | 実効チャットキー・ログ・`purpose="chat"` |
| [`src/vcenter_event_assistant/services/digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py) | `llm_digest_api_key` / `llm_digest_model` 参照 |
| [`src/vcenter_event_assistant/services/llm_tracing.py`](../../src/vcenter_event_assistant/services/llm_tracing.py) | metadata の provider/model を実効値へ |
| [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py) | 503 条件とエラーメッセージ |
| [`tests/test_llm_profile.py`](../../tests/test_llm_profile.py)（新規） | `resolve_llm_profile` / `effective_chat_api_key` |
| [`tests/test_llm_factory.py`](../../tests/test_llm_factory.py) | `purpose` と_ctor kwargs |
| [`tests/test_digest_llm.py`](../../tests/test_digest_llm.py)、[`tests/test_chat_llm.py`](../../tests/test_chat_llm.py)、[`tests/test_chat_api.py`](../../tests/test_chat_api.py)、[`tests/test_llm_tracing.py`](../../tests/test_llm_tracing.py)、[`tests/test_digest_run.py`](../../tests/test_digest_run.py)、[`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py) | `Settings` フィクスチャ更新 |
| [`.env.example`](../../.env.example)、[`docs/development.md`](../../docs/development.md) | 変数名・移行表（旧 `LLM_*` → `LLM_DIGEST_*`） |
| [`docs/superpowers/specs/2026-04-04-langsmith-tracing-design.md`](../../docs/superpowers/specs/2026-04-04-langsmith-tracing-design.md) | metadata 出所の表を実効プロファイルに合わせて更新（任意だが整合のため推奨） |

---

### Task 1: `Settings` の `llm_digest_*` / `llm_chat_*` への再定義

**Files:**
- Modify: [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py)

- [ ] **Step 1:** `llm_provider` → `llm_digest_provider`（pydantic-settings の既定ではフィールド名が大文字化され env `LLM_DIGEST_PROVIDER` になる。明示したい場合は `Field(..., description=...)` とデフォルトを維持）。同様に `llm_api_key` → `llm_digest_api_key`（env `LLM_DIGEST_API_KEY`）、`llm_base_url` → `llm_digest_base_url`、`llm_model` → `llm_digest_model`、`llm_timeout_seconds` → `llm_digest_timeout_seconds`。

- [ ] **Step 2:** 任意のチャット上書きを追加:

```python
llm_chat_provider: LlmProvider | None = Field(default=None, description="...")
llm_chat_api_key: str | None = Field(default=None, ...)
llm_chat_base_url: str | None = Field(default=None, ...)
llm_chat_model: str | None = Field(default=None, ...)
llm_chat_timeout_seconds: float | None = Field(default=None, ge=5.0, le=7200.0, ...)
```

既存の `@field_validator` でキー類の空文字 → `None` を `llm_digest_*` / `llm_chat_*` にも適用する。

- [ ] **Step 3:** リポジトリ全体を `rg 'llm_api_key|llm_provider|llm_model|llm_base_url|llm_timeout_seconds' --glob '*.py'` で置換対象を確認し、**Python ソースとテスト**を一括更新（下記タスクとまとめてでもよい）。

- [ ] **Step 4:** コミット

```bash
git add src/vcenter_event_assistant/settings.py
git commit -m "feat(settings): rename LLM_* to LLM_DIGEST_* and add LLM_CHAT_*"
```

---

### Task 2: `resolve_llm_profile` と `effective_chat_api_key`（TDD）

**Files:**
- Create: [`src/vcenter_event_assistant/services/llm_profile.py`](../../src/vcenter_event_assistant/services/llm_profile.py)
- Create: [`tests/test_llm_profile.py`](../../tests/test_llm_profile.py)

**前提:** **Task 1（Settings）が完了**し、`Settings` が `llm_digest_*` / `llm_chat_*` をコンストラクタで受け取れること。

- [ ] **Step 1: 失敗するテストを書く（RED）**

`tests/test_llm_profile.py` に以下を追加する（`Settings` のコンストラクタ引数名は Task 1 と一致させる）。

```python
"""llm_profile の単体テスト。"""

from __future__ import annotations

from vcenter_event_assistant.services.llm_profile import effective_chat_api_key, resolve_llm_profile
from vcenter_event_assistant.settings import Settings


def _base_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_digest_provider="openai_compatible",
        llm_digest_api_key="digest-key",
        llm_digest_base_url="https://api.openai.com/v1",
        llm_digest_model="digest-model",
        llm_digest_timeout_seconds=60.0,
    )


def test_resolve_digest_returns_digest_fields_only() -> None:
    s = _base_settings()
    p = resolve_llm_profile(s, purpose="digest")
    assert p.provider == "openai_compatible"
    assert p.api_key == "digest-key"
    assert p.base_url == "https://api.openai.com/v1"
    assert p.model == "digest-model"
    assert p.timeout_seconds == 60.0


def test_resolve_chat_falls_back_to_digest_when_chat_unset() -> None:
    s = _base_settings()
    p = resolve_llm_profile(s, purpose="chat")
    assert p.api_key == "digest-key"
    assert p.model == "digest-model"


def test_resolve_chat_overrides_when_llm_chat_fields_set() -> None:
    s = _base_settings()
    s = s.model_copy(
        update={
            "llm_chat_provider": "gemini",
            "llm_chat_api_key": "chat-key",
            "llm_chat_model": "chat-model",
        },
    )
    p = resolve_llm_profile(s, purpose="chat")
    assert p.provider == "gemini"
    assert p.api_key == "chat-key"
    assert p.model == "chat-model"
    assert p.base_url == "https://api.openai.com/v1"


def test_effective_chat_api_key_prefers_chat_key() -> None:
    s = _base_settings()
    s = s.model_copy(update={"llm_chat_api_key": "only-chat"})
    assert effective_chat_api_key(s) == "only-chat"


def test_effective_chat_api_key_falls_back_to_digest_key() -> None:
    s = _base_settings()
    assert effective_chat_api_key(s) == "digest-key"


def test_effective_chat_api_key_empty_when_both_empty() -> None:
    s = _base_settings()
    s = s.model_copy(update={"llm_digest_api_key": None, "llm_chat_api_key": None})
    assert effective_chat_api_key(s) == ""
```

`ResolvedLlmProfile` は `@dataclass(frozen=True)` で `provider: LlmProvider`、`api_key: str`、`base_url: str`、`model: str`、`timeout_seconds: float` とする（`api_key` は strip 済みの文字列。空は `""`）。

- [ ] **Step 2: テストを実行して RED を確認**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_llm_profile.py -v
```

期待: `resolve_llm_profile` / `ResolvedLlmProfile` が無い、または import エラーで **FAIL**。

- [ ] **Step 3: 最小実装（GREEN）**

`llm_profile.py` に `resolve_llm_profile` と `effective_chat_api_key` を実装する。チャット側のマージ規則:

- `llm_chat_provider is not None` → その値、否则 `llm_digest_provider`
- `llm_chat_api_key` が非空（strip 後）→ その値、否则 `llm_digest_api_key` の strip（`None` は `""`）
- `llm_chat_base_url` が非空 → その値、否则 `llm_digest_base_url`
- `llm_chat_model` が非空 → その値、否则 `llm_digest_model`
- `llm_chat_timeout_seconds` が `None` でない場合のみ上書き、否则 `llm_digest_timeout_seconds`（`Field(default=None)` で「未指定」を表す）

**注意:** `timeout` の「未指定」判定は `None` 必須。`float` だけだと `0` と未指定の区別が付かないため、`llm_chat_timeout_seconds: float | None = None` とする。

- [ ] **Step 4: GREEN を確認**

```bash
uv run pytest tests/test_llm_profile.py -v
```

期待: **すべて PASS**。

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/llm_profile.py tests/test_llm_profile.py
git commit -m "feat(llm): add resolve_llm_profile for digest vs chat

Digest uses LLM_DIGEST_* only; chat merges LLM_CHAT_* per field."
```

---

### Task 3: `build_chat_model` に `purpose` を追加（TDD）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py)
- Modify: [`tests/test_llm_factory.py`](../../tests/test_llm_factory.py)

- [ ] **Step 1: テストを更新（RED）**

既存の `test_build_chat_model_instantiates_expected_class` で `Settings(...)` を `llm_digest_*` に変更し、`build_chat_model(s, purpose="digest")` を呼ぶ。別パラメータ化ケースで `purpose="chat"` かつ `llm_chat_model="chat-m"` のとき ctor の `model` が `"chat-m"` になるテストを追加する。

- [ ] **Step 2:**

```bash
uv run pytest tests/test_llm_factory.py -v
```

期待: 実装未更新なら **FAIL**。

- [ ] **Step 3: 実装**

```python
from typing import Literal

from vcenter_event_assistant.services.llm_profile import resolve_llm_profile

def build_chat_model(
    settings: Settings,
    *,
    purpose: Literal["digest", "chat"],
    config: RunnableConfig | None = None,
) -> BaseChatModel:
    _ = config
    p = resolve_llm_profile(settings, purpose=purpose)
    key = p.api_key
    if p.provider == "openai_compatible":
        ...
```

- [ ] **Step 4:** `uv run pytest tests/test_llm_factory.py -v` で **PASS**。

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/llm_factory.py tests/test_llm_factory.py
git commit -m "feat(llm): build_chat_model takes purpose digest|chat"
```

---

### Task 4: `digest_llm` / `chat_llm` / `digest_run` / `chat` ルート / `llm_tracing`

**Files:**
- Modify: [`src/vcenter_event_assistant/services/digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py)
- Modify: [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)
- Modify: [`src/vcenter_event_assistant/services/digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py)
- Modify: [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py)
- Modify: [`src/vcenter_event_assistant/services/llm_tracing.py`](../../src/vcenter_event_assistant/services/llm_tracing.py)

- [ ] **digest_llm:** `settings.llm_digest_api_key` でスキップ判定。ログは `resolve_llm_profile(..., "digest")` の値を使用。`build_chat_model(..., purpose="digest")`。

- [ ] **chat_llm:** `effective_chat_api_key(settings)` でスキップ判定。ログは `resolve_llm_profile(..., "chat")`。`build_chat_model(..., purpose="chat")`。

- [ ] **digest_run:** `has_key = bool((s.llm_digest_api_key or "").strip())`、`llm_model_val = s.llm_digest_model if has_key and llm_err is None else None`。

- [ ] **chat.py:** `if not effective_chat_api_key(settings):` → 503。`detail` に「`LLM_DIGEST_API_KEY` または `LLM_CHAT_API_KEY` を設定」と日本語で記載。

- [ ] **llm_tracing:** `build_llm_runnable_config(settings, run_kind=..., ..., purpose_for_metadata: Literal["digest","chat"] | None = None)` のようにするか、`resolve_llm_profile(settings, purpose)` を呼び出し側で渡す。metadata の `llm_provider` / `llm_model` は **実効プロファイル**の文字列。

**テスト:** 既存の `test_digest_llm.py` / `test_chat_llm.py` / `test_chat_api.py` / `test_llm_tracing.py` / `test_digest_run.py` を **`Settings` の新フィールド**に合わせて更新し、`build_chat_model` の patch 対象が `purpose` を受けることを確認。

```bash
uv run pytest tests/test_digest_llm.py tests/test_chat_llm.py tests/test_chat_api.py tests/test_llm_tracing.py tests/test_digest_run.py -v
```

- [ ] **コミット**

```bash
git add src/vcenter_event_assistant/services/digest_llm.py src/vcenter_event_assistant/services/chat_llm.py \
  src/vcenter_event_assistant/services/digest_run.py src/vcenter_event_assistant/api/routes/chat.py \
  src/vcenter_event_assistant/services/llm_tracing.py tests/
git commit -m "feat(llm): wire digest/chat routes and tracing to resolved profiles"
```

---

### Task 5: 全テストとドキュメント

- [ ] **Step 1:**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest -q
```

期待: **全緑**。失敗したら該当テストの `Settings(...)` を `llm_digest_*` に直す。

- [ ] **Step 2:** [`.env.example`](../../.env.example) を `LLM_DIGEST_*` / `LLM_CHAT_*` に差し替え、**移行表**をコメントで記載する（例: `LLM_API_KEY` → `LLM_DIGEST_API_KEY`）。

- [ ] **Step 3:** [`docs/development.md`](../../docs/development.md) の LLM 節を同内容に更新。

- [ ] **Step 4: コミット**

```bash
git add .env.example docs/development.md docs/superpowers/specs/2026-04-04-langsmith-tracing-design.md
git commit -m "docs: LLM_DIGEST_* and LLM_CHAT_* env migration from LLM_*"
```

---

## 自己レビュー（プラン作成時）

1. **Spec カバレッジ:** `LLM_DIGEST_*` のみダイジェスト、`LLM_CHAT_*` フォールバック、旧 `LLM_*` 廃止、503、LangSmith metadata、DB `llm_model` はダイジェスト用 → Task 1–5 でカバー。
2. **プレースホルダ:** なし。
3. **型の一貫性:** `purpose` は `Literal["digest","chat"]`、`ResolvedLlmProfile` は Task 2 で固定。

---

**Plan complete:** [`docs/superpowers/plans/2026-04-04-llm-digest-chat-separate.md`](2026-04-04-llm-digest-chat-separate.md)

**実行の選び方:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントをdispatchし、タスク間でレビューする。必須サブスキル: `superpowers:subagent-driven-development`。
2. **インライン実行** — 同一セッションで `superpowers:executing-plans` に従い、チェックポイントでレビューする。

どちらで進めますか？
