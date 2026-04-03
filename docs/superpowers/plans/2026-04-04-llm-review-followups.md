# LLM 層レビュー追随（1〜3）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

> **TDD:** REQUIRED SUB-SKILL: **superpowers:test-driven-development** — 挙動・モジュール境界を変える箇所は **失敗するテストを先に書き、意図どおり失敗（RED）を確認してから** 実装する。実装後は **GREEN** を確認し、リファクタはテストが緑のまま行う。

## TDD の適用（タスク別）

| Task | TDD |
|------|-----|
| Task 1 | **ドキュメント・コメントのみ**（実行時挙動の変更なし）。新規テストは不要。 |
| Task 2 | **本プランの TDD 本体。** 下記「Task 2 の RED-GREEN-REFACTOR」に従う。 |
| Task 3 | **リファクタ相当**（コメント追加のみ・挙動不変）。Task 2 のテストが緑のまま `uv run pytest` で確認。 |
| Task 4 | 全件回帰。 |

### Task 2 の RED-GREEN-REFACTOR（抜粋）

1. **RED:** [`tests/test_llm_user_errors.py`](../../tests/test_llm_user_errors.py) のみ追加する。中身はプラン後段の例どおり `_llm_failure_detail_for_user(httpx.ReadTimeout(""))` と、可能なら `_is_timeout_like(APITimeoutError(...))`。**まだ** `llm_user_errors.py` を作らない、または中身を空にする。
2. **Verify RED:** `uv run pytest tests/test_llm_user_errors.py -v` — 期待: **ImportError または失敗**（モジュール／関数が無いことが原因）。
3. **GREEN:** [`llm_user_errors.py`](../../src/vcenter_event_assistant/services/llm_user_errors.py) に **`digest_llm` から移す最小実装** を書き、[`digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) / [`chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) を差し替える。既存の振る舞いは変えない。
4. **Verify GREEN:** `uv run pytest tests/test_llm_user_errors.py tests/test_digest_llm.py tests/test_chat_llm.py -v` — 期待: **PASS**。
5. **REFACTOR:** Task 3 のコメント追加。`uv run pytest -q` で緑を維持。

**禁止:** `llm_user_errors.py` の実装を先に書いてからテストを足すこと（リファクタでも同様。本タスクは「抽出」なので **テストが先**）。

---

## 設計決定（確定）

- **`build_chat_model` / [`llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py):** **維持する。** 削除、`llm_invoke` への統合、`Settings` へのメソッド移動、呼び出し側への重複実装は **行わない**（理由: DRY、[`tests/test_llm_factory.py`](../../tests/test_llm_factory.py) によるコンストラクタ引数の検証、モックのパッチ先の明確さ）。

---

**Goal:** コードレビューで挙げた改善点（1）`build_chat_model` の `config` 引数の意図明文化、（2）`_is_timeout_like` の型名ヒューリスティックの意図コメント、（3）タイムアウト／ユーザー向けエラー文言を [`llm_user_errors.py`](../../src/vcenter_event_assistant/services/llm_user_errors.py) に集約して `digest_llm` の `httpx` 直接依存を整理する。

**Architecture:** [`llm_factory.build_chat_model`](../../src/vcenter_event_assistant/services/llm_factory.py) は **残したまま** docstring の `Args` を補足する。エラー文言・タイムアウト判定は **`digest_llm` から `llm_user_errors` へ抽出**し、`chat_llm` の import を差し替える。

**Tech Stack:** Python 3.12、`httpx`、`openai`（任意）、`pytest`。

---

## ファイル構成

| パス | 変更 |
|------|------|
| 変更 [`llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py) | docstring / `config` のコメントのみ（**シグネチャは維持**） |
| 新規 [`llm_user_errors.py`](../../src/vcenter_event_assistant/services/llm_user_errors.py) | `_is_timeout_like`、`_llm_failure_detail_for_user` |
| 変更 [`digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) | 上記を削除し import。`httpx` / `asyncio` を削減 |
| 変更 [`chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | `_llm_failure_detail_for_user` の import 元を変更 |
| 新規 [`tests/test_llm_user_errors.py`](../../tests/test_llm_user_errors.py) | タイムアウト文言の最小テスト |

---

### Task 1: `llm_factory.build_chat_model` のドキュメント整備

**Files:** [`llm_factory.py`](../../src/vcenter_event_assistant/services/llm_factory.py)

**TDD:** 挙動変更なしのためテスト追加なし。

- [ ] docstring に **Args** を追記: `config` は **invoke/astream 時**に `stream_chat_to_text` 等へ渡す `RunnableConfig` 用。モデルコンストラクタにはバインドせず、**本関数内では現状未使用**。
- [ ] `_ = config` 直前に 1 行コメント（シグネチャ互換・callbacks は invoke 時）。
- [ ] コミット: `docs(llm): clarify RunnableConfig on build_chat_model`

### Task 2: `llm_user_errors` の抽出と import 差し替え

**Files:** 上記「ファイル構成」および **「Task 2 の RED-GREEN-REFACTOR」** 参照。

- [ ] **Step A（RED）:** [`tests/test_llm_user_errors.py`](../../tests/test_llm_user_errors.py) を追加（下記コードブロックを満たすこと）。

```python
"""llm_user_errors の振る舞いテスト（TDD: 先にこれを書く）。"""

from __future__ import annotations

import httpx
import pytest


def test_llm_failure_detail_timeout_uses_japanese_hint() -> None:
    from vcenter_event_assistant.services.llm_user_errors import _llm_failure_detail_for_user

    d = _llm_failure_detail_for_user(httpx.ReadTimeout(""))
    assert "タイムアウト" in d
    assert "LLM_TIMEOUT_SECONDS" in d


def test_is_timeout_like_matches_apitimeout_if_openai_installed() -> None:
    from vcenter_event_assistant.services.llm_user_errors import _is_timeout_like

    try:
        from openai import APITimeoutError
    except ImportError:
        pytest.skip("openai not installed")
    assert _is_timeout_like(APITimeoutError("x")) is True
```

- [ ] **Step B:** `uv run pytest tests/test_llm_user_errors.py -v` — 期待: **失敗**（ImportError または AssertionError）。
- [ ] **Step C（GREEN）:** `llm_user_errors.py` を実装し、`digest_llm` / `chat_llm` から関数を移動・import 差し替え。
- [ ] **Step D:** `uv run pytest tests/test_llm_user_errors.py tests/test_digest_llm.py tests/test_chat_llm.py -v` — 期待: **PASS**。
- [ ] **Step E:** コミット: `refactor(llm): extract user-facing error helpers to llm_user_errors`

### Task 3: `_is_timeout_like` のヒューリスティックに日本語コメント

**Files:** [`llm_user_errors.py`](../../src/vcenter_event_assistant/services/llm_user_errors.py)

**TDD:** 挙動不変のリファクタ。新規テストは不要（既存テストが緑のまま）。

- [ ] `type(exc).__name__` に `"timeout"` を含む分岐の直前に、SDK 差対応と誤検知の可能性に触れる短いコメント。
- [ ] `uv run pytest -q` — 期待: **PASS**。
- [ ] コミット: `docs(llm): explain timeout heuristic in _is_timeout_like`

### Task 4: 回帰

- [ ] `uv run pytest -q`（プロジェクト全体）

---

## 実行オプション

1. **Subagent-Driven** — superpowers:subagent-driven-development  
2. **Inline** — superpowers:executing-plans  
