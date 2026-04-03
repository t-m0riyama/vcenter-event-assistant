# ストリーミング LLM 応答のコンテンツブロック正規化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemini 等が `astream` の各チャンクで `content` を `list[dict]`（`type: "text"` ブロック）として返す場合でも、チャット・ダイジェストの assistant 本文が **プレーンテキスト**として API 経由でフロントに届くようにする（`str(list)` 連結による repr 表示を防ぐ）。

**Architecture:** 集約点は [`src/vcenter_event_assistant/services/llm_invoke.py`](../../src/vcenter_event_assistant/services/llm_invoke.py) の `stream_chat_to_text` のみ。`langchain_core` の `BaseMessageChunk` が提供する **`text` プロパティ**（文字列 `content` とブロック配列 `content` の両方からテキスト部分を連結）をストリーム各チャンクに対して使い、連結する。フロントエンド・OpenAPI スキーマは変更不要（`ChatMessage.content` は引き続き `str`）。

**Tech Stack:** Python 3.12+、`uv`、`langchain-core`（`AIMessageChunk` / `BaseMessage.text`）、`pytest`、`pytest-asyncio`。

**TDD（本プラン）:** **先に** [`tests/test_llm_invoke.py`](../../tests/test_llm_invoke.py) に失敗するテストを追加し、`pytest` で **RED** を確認してから** `llm_invoke` を最小修正して **GREEN**。リファクタはテストが緑のまま。

---

## ファイル構成（作成・変更の地図）

| パス | 役割 |
|------|------|
| 変更 [`src/vcenter_event_assistant/services/llm_invoke.py`](../../src/vcenter_event_assistant/services/llm_invoke.py) | `str(chunk.content)` をやめ、`chunk.text`（または同等のテキスト抽出）で連結。docstring に 1 行で理由を追記。 |
| 新規 [`tests/test_llm_invoke.py`](../../tests/test_llm_invoke.py) | `stream_chat_to_text` のブロック形式チャンク結合を固定する非ネットワークテスト。 |
| 参照のみ（変更しない） | [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)、[`src/vcenter_event_assistant/services/digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) — 両方とも `stream_chat_to_text` を呼ぶだけなので、上記 1 ファイル修正で両経路が直る。 |

---

### Task 1: `stream_chat_to_text` のコンテンツブロック結合（TDD）

**Files:**
- Create: [`tests/test_llm_invoke.py`](../../tests/test_llm_invoke.py)
- Modify: [`src/vcenter_event_assistant/services/llm_invoke.py`](../../src/vcenter_event_assistant/services/llm_invoke.py)

#### Step 1: 失敗するテストを書く（RED）

新規ファイル [`tests/test_llm_invoke.py`](../../tests/test_llm_invoke.py) に、次の **完全な** テストを追加する。`astream` を持つ最小のダミーモデルが `AIMessageChunk`（`content` がブロックのリスト）を返す。期待する振る舞いは **結合結果が `"あい"`** であり、**Python の `list` の repr（`[` で始まる文字列）を含まない**こと。

```python
"""llm_invoke.stream_chat_to_text のテスト。"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage

from vcenter_event_assistant.services.llm_invoke import stream_chat_to_text


@pytest.mark.asyncio
async def test_stream_chat_to_text_joins_plain_text_from_content_blocks() -> None:
    """Gemini 等: チャンクの content が list[dict] のときもプレーンテキストとして連結する。"""
    chunks = [
        AIMessageChunk(content=[{"type": "text", "text": "あ", "index": 0}]),
        AIMessageChunk(content=[{"type": "text", "text": "い", "index": 0}]),
    ]

    class _FakeStreamModel:
        async def astream(self, messages: object, config: object = None):
            _ = messages
            _ = config
            for c in chunks:
                yield c

    out = await stream_chat_to_text(
        _FakeStreamModel(),  # type: ignore[arg-type]
        [HumanMessage("hi")],
    )
    assert out == "あい"
    assert "[" not in out
```

- [ ] 上記ファイルを保存する。

#### Step 2: RED を確認する

リポジトリルートで実行する。

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run pytest tests/test_llm_invoke.py::test_stream_chat_to_text_joins_plain_text_from_content_blocks -v
```

- [ ] **期待:** 失敗（FAIL）。アサーション `assert out == "あい"` または `assert "[" not in out` が落ちる。現行実装は `str(chunk.content)` のため、`[` を含む文字列になる。

#### Step 3: 最小実装（GREEN）

[`src/vcenter_event_assistant/services/llm_invoke.py`](../../src/vcenter_event_assistant/services/llm_invoke.py) の `stream_chat_to_text` 内ループを次のように変更する（`chunk` は `BaseMessageChunk` 子クラスであり `.text` でテキスト抽出可能）。

```python
    parts: list[str] = []
    async for chunk in model.astream(messages, config=config):
        if chunk.content:
            parts.append(str(chunk.text))
```

docstring の説明文に、次の 1 文を追記する（日本語で可）。

- 「一部プロバイダでは `content` が文字列ではなくテキストブロックの配列になるため、`str(content)` は使わず `text` で抽出する。」

- [ ] 保存する。

#### Step 4: GREEN を確認する

```bash
uv run pytest tests/test_llm_invoke.py::test_stream_chat_to_text_joins_plain_text_from_content_blocks -v
```

- [ ] **期待:** PASS。

#### Step 5: 回帰確認（全体）

```bash
uv run pytest
```

- [ ] **期待:** 全テスト PASS（既存の `test_chat_llm` 等も含む）。

#### Step 6: コミット

Conventional Commits に従い、タイトル短く、本文に詳細。

```bash
git add src/vcenter_event_assistant/services/llm_invoke.py tests/test_llm_invoke.py
git commit -m "fix(llm): normalize streaming chunks with content blocks for Gemini"
```

（本文に「`str(chunk.content)` が list repr になる問題」「`chunk.text` で修正」「チャット・ダイジェスト共通」を 2〜4 文で書く。）

- [ ] コミットする。

---

## 自己レビュー（プラン作成時チェック）

1. **Spec coverage:** UI に JSON 風 repr が出る原因（`stream_chat_to_text` の `str(chunk.content)`）に対し、単一集約点の修正と回帰テストでカバー。フロント変更は不要と明記。
2. **Placeholder スキャン:** タスク内に TBD / 「適宜」なし。コードブロックは実装可能な完全形。
3. **型・API 整合:** `chunk.text` は `langchain_core` の `BaseMessage` に定義済み。`# type: ignore[arg-type]` はテストのダミーモデル用のみ。

---

## 実行の引き渡し

**プランは `docs/superpowers/plans/2026-04-04-stream-chat-content-blocks-fix.md` に保存済み。実行方法は次のいずれか。**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビューする。必須サブスキル: `superpowers:subagent-driven-development`。
2. **インライン実行** — 同一セッションで `superpowers:executing-plans` に従いチェックポイント付きで一括実行。

**どちらで進めますか？**
