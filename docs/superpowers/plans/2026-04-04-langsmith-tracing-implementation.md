# LangSmith Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** LangSmith 向けトレーシングを設定でオンにしたときだけ有効化し、`period_chat` と `digest` を `tags` / `metadata` で区別する。

**Architecture:** `Settings` の `langsmith_*` と [`llm_tracing.build_llm_runnable_config`](../src/vcenter_event_assistant/services/llm_tracing.py) により `RunnableConfig` を組み立て、[`api/routes/chat.py`](../src/vcenter_event_assistant/api/routes/chat.py) と [`digest_run.run_digest_once`](../src/vcenter_event_assistant/services/digest_run.py) から注入する。

**Tech Stack:** Python 3.12+、`uv`、`langsmith`、`langchain-core`。

**設計書:** [`docs/superpowers/specs/2026-04-04-langsmith-tracing-design.md`](../specs/2026-04-04-langsmith-tracing-design.md)

---

## タスク完了状況（実装済み）

- [x] Task 1: 設計書
- [x] Task 2: `uv add langsmith`
- [x] Task 3: `Settings` に LangSmith フィールド
- [x] Task 4–6: `tests/test_llm_tracing.py` と `llm_tracing.py`
- [x] Task 7: `chat.py` / `digest_run.py` 配線
- [x] Task 8: `test_run_period_chat_passes_runnable_config_to_stream`
- [x] Task 9–10: `.env.example`、`docs/development.md`、ruff・pytest
