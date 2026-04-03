# LangChain LLM 層置き換え Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `httpx` 直叩きの LLM 呼び出し（ダイジェスト要約・期間チャット）を LangChain の `BaseChatModel`（`langchain-openai` / `langchain-google-genai`）に置き換え、将来 LangSmith 用の `callbacks` 注入点を用意する（LangSmith 本体は未実装）。

**Architecture:** `Settings` から `ChatOpenAI` または `ChatGoogleGenerativeAI` を組み立てるファクトリ（単一モジュール）を追加する。プロンプト組み立て・`tiktoken` による入力バジェット・`ChatLlmContextMeta` は既存ロジックを維持し、**最終的な `BaseMessage` 列の生成から応答テキスト取得まで**を LangChain に委譲する。エラー文言・フォールバック（API キーなし・失敗時）は現行のユーザー向け挙動をテストで固定する。

**Tech Stack:** Python 3.12+、`uv`、`langchain-core`、`langchain-openai`、`langchain-google-genai`、既存の `tiktoken`・`pytest`・`pytest-asyncio`。

**前提ドキュメント:** 設計レビュー用の [`docs/superpowers/specs/2026-04-04-langchain-llm-design.md`](2026-04-04-langchain-llm-design.md) が未作成なら、実装着手前に短い設計（設定対応表・スコープ外・LangSmith 拡張点）をここに追記または別ファイルで作成する。

**TDD（本プラン共通）:** 各タスクでは **先にテストを追加または変更し、期待どおり失敗（RED）を確認してから** 実装する。実装後に **GREEN** を確認し、リファクタはテストが緑のまま行う。リファクタリングのみの既存挙動は、**振る舞いを変える前に** 現在のテストがその挙動を表していることを確認する。

---

## ファイル構成（作成・変更の地図）

| パス | 役割 |
|------|------|
| 新規 [`src/vcenter_event_assistant/services/llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py) | `Settings` → `BaseChatModel`。`llm_provider` で分岐。タイムアウト・`base_url`・モデル名を設定。任意で `RunnableConfig` 用の `callbacks` を後から差し込めるよう、ファクトリ引数で受け取る（既定 `None`）。 |
| 変更 [`src/vcenter_event_assistant/services/digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) | `httpx` / SSE 手書きを削除。`llm_factory.build_chat_model` + `SystemMessage`/`HumanMessage` + `ainvoke` または `astream`（後述）で要約取得。`_llm_failure_detail_for_user` 等は可能な限り維持。 |
| 変更 [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | 同上。マルチターンは `messages` を LangChain の `HumanMessage`/`AIMessage` に変換。Gemini パスも統合クラスへ。 |
| 変更 [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | 必要なら LangChain が期待するパラメータ名へエイリアス（ユーザー合意済み: 破壊的変更可）。 |
| 変更 [`pyproject.toml`](../../pyproject.toml) / lock | 上記依存を `uv add` で追加。 |
| 変更 [`tests/test_llm_factory.py`](../../tests/test_llm_factory.py) | 新規。ファクトリの分岐とコンストラクタ引数。 |
| 変更 [`tests/test_digest_llm.py`](../../tests/test_digest_llm.py) | `httpx` モックをやめ、`FakeListChatModel` または `build_chat_model` のパッチで振る舞い検証。 |
| 変更 [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py) | 同上。`captured["messages"]` は `ainvoke` に渡した `messages` を取得する方法に変更（下記 Task のコード参照）。 |
| 変更 [`README.md`](../../README.md) または [`docs/development.md`](../../docs/development.md) | 環境変数の変更があれば表で記載。 |

**ストリーミング方針:** 現状は OpenAI 互換で `stream: true`。Ollama 等の長時間生成を考慮し、実装では **`astream` でチャンクを連結**し、空完了は現行同様エラーとする。テストはネットワークなしで `FakeListChatModel`（`ainvoke`）で足りる場合が多いが、`astream` 経路を通す場合は `unittest.mock.AsyncMock` で `astream` をモックするタスクを 1 本含める。

---

### Task 0: ブランチとワークツリー

**Files:** なし（git のみ）

- [ ] **Step 1:** ルールに従い、`main` 直コミットを避け、`feature/langchain-llm` 等のブランチで作業する（既存の worktree 運用があればそれに従う）。
- [ ] **Step 2:** `git status` でクリーンな作業ツリーから開始する。

---

### Task 1: 依存追加（テストなし・ロック更新）

**Files:**
- Modify: [`pyproject.toml`](../../pyproject.toml)
- Modify: `uv.lock`（生成）

- [ ] **Step 1:** リポジトリルートで実行する。

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv add langchain-core langchain-openai langchain-google-genai
```

- [ ] **Step 2:** `uv sync` が成功することを確認する。

```bash
uv sync
```

期待: 終了コード 0。

- [ ] **Step 3:** コミットする。

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add langchain-core, langchain-openai, langchain-google-genai"
```

---

### Task 2: `llm_factory` の TDD（ファクトリのみ）

**Files:**
- Create: [`src/vcenter_event_assistant/services/llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py)
- Create: [`tests/test_llm_factory.py`](../../tests/test_llm_factory.py)

- [ ] **Step 1: 失敗するテストを書く（RED）**

`tests/test_llm_factory.py` に以下を追加する（`build_chat_model` は未実装のため ImportError または失敗する）。

```python
"""llm_factory.build_chat_model の単体テスト（ネットワークなし）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vcenter_event_assistant.settings import Settings


@pytest.mark.parametrize(
    ("provider", "target", "model_cls"),
    [
        ("openai_compatible", "langchain_openai.ChatOpenAI", "ChatOpenAI"),
        ("gemini", "langchain_google_genai.ChatGoogleGenerativeAI", "ChatGoogleGenerativeAI"),
    ],
)
def test_build_chat_model_instantiates_expected_class(
    provider: str,
    target: str,
    model_cls: str,
) -> None:
    from vcenter_event_assistant.services import llm_factory

    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="k",
        llm_provider=provider,  # type: ignore[arg-type]
        llm_base_url="https://api.openai.com/v1",
        llm_model="m",
        llm_timeout_seconds=30.0,
    )
    with patch(target) as ctor:
        mock_instance = MagicMock(name=model_cls)
        ctor.return_value = mock_instance
        out = llm_factory.build_chat_model(s)
        assert out is mock_instance
        ctor.assert_called_once()
        call_kw = ctor.call_args.kwargs
        assert call_kw.get("model") == "m"
        assert call_kw.get("api_key") == "k"
        if provider == "openai_compatible":
            assert call_kw.get("base_url") == "https://api.openai.com/v1"
```

- [ ] **Step 2: テストを実行し、失敗を確認する。**

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run pytest tests/test_llm_factory.py -v
```

期待: `ModuleNotFoundError` または `ImportError`（`llm_factory` 未作成）または `AttributeError`（`build_chat_model` 未定義）。

- [ ] **Step 3: 最小実装（GREEN）**

`src/vcenter_event_assistant/services/llm_factory.py`:

```python
"""Settings から LangChain ChatModel を組み立てる。"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from vcenter_event_assistant.settings import Settings


def build_chat_model(
    settings: Settings,
    *,
    config: RunnableConfig | None = None,
) -> BaseChatModel:
    """
    LLM 設定に応じて ChatModel を返す。

    ``config`` は将来 LangSmith 等の callbacks を渡すための拡張点として受け取る。
    現状はモデル構築にのみ用い、未使用でもよい。
    """
    _ = config  # 将来: ChatModel にバインドするか、invoke 時に渡す
    key = (settings.llm_api_key or "").strip()
    if settings.llm_provider == "openai_compatible":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            api_key=key,
            base_url=settings.llm_base_url.rstrip("/"),
            timeout=settings.llm_timeout_seconds,
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=key,
        timeout=settings.llm_timeout_seconds,
    )
```

**注意:** `ChatGoogleGenerativeAI` の引数名は実装時のパッケージドキュメントに合わせる（`google_api_key` vs `api_key`）。テストの `call_kw` アサーションを実際の SDK に合わせて修正する。

- [ ] **Step 4: テストが通ることを確認する。**

```bash
uv run pytest tests/test_llm_factory.py -v
```

期待: 全テスト PASS。

- [ ] **Step 5: コミットする。**

```bash
git add src/vcenter_event_assistant/services/llm_factory.py tests/test_llm_factory.py
git commit -m "feat: add llm_factory.build_chat_model for OpenAI-compatible and Gemini"
```

---

### Task 3: `digest_llm` を LangChain へ（TDD）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py)
- Modify: [`tests/test_digest_llm.py`](../../tests/test_digest_llm.py)

**方針:** 既存の `test_augment_openai_merges_summary` 等を、**一度** `FakeListChatModel` と `monkeypatch` で `build_chat_model` を差し替える形に書き換える（RED: 実装がまだ `httpx` のままなら「想定したモデルが呼ばれない」または接続しようとして失敗）。

- [ ] **Step 1: テストの先頭で `FakeListChatModel` を使うヘルパを追加し、`test_augment_openai_merges_summary` を次の形に変更する（RED）。**

```python
from langchain_core.language_models.fake import FakeListChatModel

# テスト内:
async def test_augment_openai_merges_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        llm_api_key="sk-test",
        llm_provider="openai_compatible",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
    )
    fake = FakeListChatModel(responses=["## LLM 要約\n- テスト"])

    def _fake_build(_settings: Settings) -> FakeListChatModel:
        assert _settings is s
        return fake

    monkeypatch.setattr(
        "vcenter_event_assistant.services.digest_llm.build_chat_model",
        _fake_build,
    )
    out, err = await augment_digest_with_llm(s, context=_minimal_ctx(), template_markdown="# base")
    ...
```

期待 RED: `digest_llm` がまだ `httpx` なら、パッチが効かず従来どおり httpx が呼ばれる、または `build_chat_model` が import されていない。

- [ ] **Step 2: `digest_llm.augment_digest_with_llm` を実装し、`langchain_core.messages` の `SystemMessage` / `HumanMessage` で `fake.ainvoke` が呼ばれるようにする（GREEN）。**

応答連結は `ainvoke` の戻り `AIMessage.content` を `str` 化して使用。ストリーミングが必須なら `_stream_to_text` ヘルパで `astream` を連結し、同テストで `FakeListChatModel` が `astream` をサポートするか確認（未対応なら `test_digest_llm` は `ainvoke` 経路で統一し、`astream` は `AsyncMock` で別テスト）。

- [ ] **Step 3:** `test_augment_gemini_merges_summary`・エラー系・タイムアウト系を同パターンに移植する。`test_augment_returns_template_on_http_error` は `FakeListChatModel` で例外を起こすのではなく、`augment_digest_with_llm` 内で `ainvoke` を `monkeypatch` して `RuntimeError("HTTP 500")` を投げるか、`build_chat_model` が例外を投げるモックを使う。

- [ ] **Step 4:** `httpx` の import と SSE パーサを削除できることを確認する。

```bash
uv run pytest tests/test_digest_llm.py -v
```

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/digest_llm.py tests/test_digest_llm.py
git commit -m "refactor: use LangChain ChatModel for digest LLM"
```

---

### Task 4: `chat_llm` を LangChain へ（TDD）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)
- Modify: [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py)

- [ ] **Step 1:** `digest_llm` から `chat_llm` が import している `_collect_openai_chat_stream_text` 等が削除された場合、`chat_llm` 側で LangChain に完全移行するか、共有ヘルパ `_stream_to_text(model, messages, config)` を新規小モジュールに切り出す。

- [ ] **Step 2: RED** — `test_run_period_chat_openai_sends_multiturn_and_returns_assistant_text` で `httpx` の代わりに `build_chat_model` を `FakeListChatModel` にパッチし、**LangChain に渡るメッセージ列**を検証する。`captured` は次のように取得する。

```python
captured: dict[str, object] = {}

async def _spy_ainvoke(self: object, messages: object, *a: object, **kw: object) -> object:
    captured["lc_messages"] = messages
    from langchain_core.messages import AIMessage

    return AIMessage(content="追質問への回答")

monkeypatch.setattr(
    FakeListChatModel,
    "ainvoke",
    _spy_ainvoke,
)
```

（`FakeListChatModel` のサブクラスをテスト内で定義して `ainvoke` をオーバーライドする方法でもよい。）

- [ ] **Step 3: GREEN** — `run_period_chat` 内で `build_chat_model` を呼び、組み立てた `messages` で `ainvoke`（または `astream`）する。`_CHAT_SYSTEM_PROMPT` と JSON ブロック・会話履歴の構造は現行テストのアサーションと一致させる。

- [ ] **Step 4:** `test_run_period_chat_gemini_returns_text`・トークン切り詰め・`period_metrics`・`event_time_buckets` を同様に更新する。

```bash
uv run pytest tests/test_chat_llm.py -v
```

- [ ] **Step 5: コミット**

```bash
git add src/vcenter_event_assistant/services/chat_llm.py tests/test_chat_llm.py
git commit -m "refactor: use LangChain ChatModel for period chat"
```

---

### Task 5: API ルートと統合テスト

**Files:**
- Read: [`tests/test_chat_api.py`](../../tests/test_chat_api.py)

- [ ] **Step 1:** `uv run pytest tests/test_chat_api.py -v` を実行し、モックが `run_period_chat` を指しているため **そのまま通る**ことを確認する。

- [ ] **Step 2:** 失敗があれば、`run_period_chat` のシグネチャや戻り値が変わっていないか確認して修正する。

```bash
uv run pytest tests/ -v --tb=short
```

---

### Task 6: ドキュメントと設定の破壊的変更の記載

**Files:**
- Modify: [`README.md`](../../README.md) または [`docs/development.md`](../../docs/development.md)

- [ ] **Step 1:** `LLM_*` 環境変数の対応表（旧 → 新）を追記する。`ChatGoogleGenerativeAI` のキー名が `.env` の例と異なる場合は `.env.example` があれば更新する。

- [ ] **Step 2:** コミットする。

```bash
git add README.md docs/development.md .env.example
git commit -m "docs: document LLM env vars after LangChain migration"
```

---

## 自己レビュー（プラン vs 実装前チェック）

1. **Spec カバレッジ:** 設計にあった「LangSmith 用 `callbacks` 拡張点」→ Task 2 の `build_chat_model(..., config=)` と、invoke 時に `config` を渡すかどうかがプランに明示されていれば十分。実装時、`run_period_chat` / `augment_digest_with_llm` の `ainvoke(messages, config=config)` を仕上げタスクで追加する 1 行を入れるなら Task 2 または Task 4 に追記する。
2. **プレースホルダ:** 上記 `ChatGoogleGenerativeAI` のパラメータ名は実パッケージで確定させる（プラン内「注意」で吸収済み）。
3. **型の一貫性:** `llm_provider` の型は `Settings` の `Literal` と一致させる。

## 設計決定の追記（レビュー後）

- **`build_chat_model` と [`llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py):** **維持する。** ファクトリを `llm_invoke` に統合したり、`Settings` のメソッドへ移したり、関数を削除して `digest_llm` / `chat_llm` に同じ分岐を重複実装することは **行わない**（DRY・単体テストのパッチ先の明確さのため）。

---

## 完了後の実行オプション

**Plan complete and saved to `docs/superpowers/plans/2026-04-04-langchain-llm-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — タスクごとに新しい subagent を起動し、タスク間でレビューする（**REQUIRED SUB-SKILL:** superpowers:subagent-driven-development）。

**2. Inline Execution** — 同一セッションで executing-plans に従いチェックポイント付きで実行する（**REQUIRED SUB-SKILL:** superpowers:executing-plans）。

**Which approach?**
