# バックエンド設計改善 Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** `main.py` の責務分離、不要な settings 引数の引き回し排除、および `chat_llm.py` 内のロジック重複を解消する。

**Architecture:** インライン定義された ingest エンドポイントを専用ルーターモジュールに抽出し、DI に依存しないグローバルな設定（`get_settings()`）の直接呼び出しへ移行。重複する LLM 用の JSON/会話構築ロジックを共通関数にまとめます。

**Tech Stack:** Python, FastAPI, Pydantic

---

### Task 1: `ingest` ルーターの分離

**Files:**
- Create: `src/vcenter_event_assistant/api/routes/ingest.py`
- Modify: `src/vcenter_event_assistant/main.py`
- Test: `tests/test_vcenter_proxy_connection.py` 等（既存のテストでAPIの統合を検証）

**Step 1: 新規ルーターモジュールの作成**

`src/vcenter_event_assistant/api/routes/ingest.py` を作成し、`main.py` から `run_ingest_now` のロジックを移動します。

```python
"""手動インジェストエンドポイント。"""

from fastapi import APIRouter
from sqlalchemy import select

from vcenter_event_assistant.db.models import VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
    list_enabled_vcenters,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/run")
async def run_ingest_now() -> dict[str, str | int]:
    async with session_scope() as session:
        vcenters = await list_enabled_vcenters(session)
        ids = [v.id for v in vcenters]
    ev_total = 0
    m_total = 0
    for vid in ids:
        async with session_scope() as session:
            res = await session.execute(select(VCenter).where(VCenter.id == vid))
            vc = res.scalar_one()
            ev_total += await ingest_events_for_vcenter(session, vc)
        async with session_scope() as session:
            res = await session.execute(select(VCenter).where(VCenter.id == vid))
            vc = res.scalar_one()
            m_total += await ingest_metrics_for_vcenter(session, vc)
    return {"status": "ok", "events_inserted": ev_total, "metrics_inserted": m_total}
```

**Step 2: `main.py` の修正**

`src/vcenter_event_assistant/main.py` からインラインの `@api.post("/ingest/run")` 定義（約25行）を削除し、インポート文とルーター登録を追加します。

```python
# インポート部に追加
from vcenter_event_assistant.api.routes.ingest import router as ingest_router

# api.include_router(...) が並んでいる箇所に追加
api.include_router(ingest_router)
```

**Step 3: テスト実行とコミット**

Run: `uv run pytest`
Expected: すべてのテストがPASSすること

```bash
git add src/vcenter_event_assistant/main.py src/vcenter_event_assistant/api/routes/ingest.py
git commit -m "refactor: extract ingest router from main.py"
```

---

### Task 2: `chat_llm.py` の重複ロジック抽出と settings 引き回しの排除

**Files:**
- Modify: `src/vcenter_event_assistant/services/chat_llm.py`
- Modify: `src/vcenter_event_assistant/api/routes/chat.py` (settings 引き渡し箇所)
- Test: `tests/test_chat_llm.py`

**Step 1: 共通関数 `_build_chat_context_and_meta` の作成**

`chat_llm.py` 内に以下を追加し、引数から `settings` を削除します。内部で `get_settings()` を呼びます。

```python
from vcenter_event_assistant.settings import get_settings

def _build_chat_context_and_meta(
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    extra_vcenter_strings: Sequence[str] | None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta, dict[str, str]]:
    settings = get_settings()
    payload, trimmed_msgs, reverse_map = _prepare_chat_payload(
        settings, context, messages,
        period_metrics, event_time_buckets, extra_vcenter_strings,
    )
    ctx_json, trimmed, json_truncated = _fit_chat_payload_to_token_budget(settings, payload, trimmed_msgs)
    block = _merged_context_user_block(ctx_json)
    est_tokens = _estimate_chat_input_tokens(block, trimmed)
    meta = ChatLlmContextMeta(
        json_truncated=json_truncated,
        estimated_input_tokens=est_tokens,
        max_input_tokens=settings.llm_chat_max_input_tokens,
        message_turns=len(trimmed),
    )
    return block, trimmed, meta, reverse_map
```

**Step 2: `build_chat_preview` と `run_period_chat` のリファクタリング**

両関数から `settings: Settings` 引数を削除（または非推奨として削除）し、上記ヘルパーを呼び出します。

```python
def build_chat_preview(
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[str, list[ChatMessage], ChatLlmContextMeta | None]:
    block, trimmed, meta, _ = _build_chat_context_and_meta(
        context, messages, period_metrics, event_time_buckets, extra_vcenter_strings
    )
    return block, trimmed, meta

async def run_period_chat(
    *,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None = None,
    event_time_buckets: EventTimeBucketsPayload | None = None,
    runnable_config: RunnableConfig | None = None,
    extra_vcenter_strings: Sequence[str] | None = None,
) -> tuple[str, str | None, ChatLlmContextMeta | None, int | None, float | None]:
    settings = get_settings()
    if not is_chat_llm_configured(settings):
        return ("", None, None, None, None)

    block, trimmed, meta, reverse_map = _build_chat_context_and_meta(
        context, messages, period_metrics, event_time_buckets, extra_vcenter_strings
    )
    # 以下、既存の try ブロックを維持（block, trimmed, meta を利用）
```

**Step 3: APIルート等の呼び出し元から `settings` 引数を削除**

`src/vcenter_event_assistant/api/routes/chat.py` 内の `run_period_chat` や `build_chat_preview` の呼び出し箇所から `settings=...` 引数を削除します。
※ 他モジュールやテスト（`tests/test_chat_llm.py` など）で `settings` を渡している箇所があれば、全て対応して引数エラーを解消します。

**Step 4: テスト実行とコミット**

Run: `uv run pytest`
Expected: すべてのテストがPASSすること

```bash
git add src/vcenter_event_assistant/services/chat_llm.py src/vcenter_event_assistant/api/routes/chat.py tests/
git commit -m "refactor: deduplicate chat logic and drop settings injection"
```
