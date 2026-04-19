# Chat Prompt Preview Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** チャット送信前にバックエンドで生成される最終的なユーザープロンプト（コンテキストJSON＋会話履歴）を確認できるプレビュー機能を追加する。

**Architecture:** バックエンドにLLM呼び出しをスキップしてプロンプト構築結果だけを返す `POST /api/chat/preview` エンドポイントを新設し、フロントエンドのチャットパネルにプレビュー用モーダルを追加してその結果を表示する。

**Tech Stack:** FastAPI, Pydantic, React, TypeScript, Vitest

---

### Task 1: Backend API Schemas & Route

**Files:**
- Modify: `src/vcenter_event_assistant/api/schemas.py`
- Modify: `src/vcenter_event_assistant/api/routes/chat.py`

**Step 1: Write the failing test**

`tests/test_chat_preview_api.py` を新規作成し、`/api/chat/preview` にPOSTリクエストを送るテストを記述する。

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_post_chat_preview_success(client: AsyncClient, mocker):
    mocker.patch("vcenter_event_assistant.services.llm_profile.is_chat_llm_configured", return_value=True)
    mocker.patch("vcenter_event_assistant.api.routes.chat.build_digest_context")
    req = {
        "from_time": "2024-01-01T00:00:00Z",
        "to_time": "2024-01-01T01:00:00Z",
        "messages": [{"role": "user", "content": "test"}]
    }
    resp = await client.post("/api/chat/preview", json=req)
    assert resp.status_code == 200
    data = resp.json()
    assert "context_block" in data
    assert "conversation" in data
    assert "llm_context" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chat_preview_api.py -v`
Expected: FAIL (404 Not Found または実装が未定義エラー)

**Step 3: Write minimal implementation**

`src/vcenter_event_assistant/api/schemas.py`: `ChatPreviewResponse` を追加。
```python
from pydantic import BaseModel
from vcenter_event_assistant.api.schemas import ChatMessage, ChatLlmContextMeta

class ChatPreviewResponse(BaseModel):
    context_block: str
    conversation: list[ChatMessage]
    llm_context: ChatLlmContextMeta | None
```

`src/vcenter_event_assistant/api/routes/chat.py`: `/api/chat/preview` を既存の `/api/chat` のロジックを流用して作成。 LLM呼び出し (`run_period_chat`) の前に返却するようにし、`_fit_chat_payload_to_token_budget` などの共通ロジックを抽出またはモック。
*(※ 実際は `services/chat_llm.py` の `_fit_chat_payload_to_token_budget` 等を呼び出して構造を準備する関数を新設するか、`chat.py` 側で組み立てる)*

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_preview_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/vcenter_event_assistant/api/schemas.py src/vcenter_event_assistant/api/routes/chat.py tests/test_chat_preview_api.py
git commit -m "feat: add /api/chat/preview endpoint"
```

### Task 2: Backend Service Refactoring for Preview (If needed based on Task 1 implementation)

**Files:**
- Modify: `src/vcenter_event_assistant/services/chat_llm.py`
- Modify: `tests/test_chat_llm.py`

**Step 1: Write the failing test**

`tests/test_chat_llm.py` にプレビュー作成用ロジックのテストを追加。

**Step 2: Run test to verify it fails**
Run: `pytest tests/test_chat_llm.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

`run_period_chat` 内で行われている「JSONの切り詰めとトークン計算」部分を `build_chat_preview` のような関数として切り出し、APIから呼べるようにする。

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chat_llm.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/chat_llm.py tests/test_chat_llm.py 
git commit -m "refactor: extract chat preview logic"
```

### Task 3: Frontend API & Types

**Files:**
- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/schemas.test.ts`

**Step 1: Write the failing test**

`frontend/src/api/schemas.test.ts` に `ChatPreviewResponse` のparseテストを追加。

**Step 2: Run test to verify it fails**

Run: `npm test -- -t "chatPreviewResponse"`
Expected: FAIL

**Step 3: Write minimal implementation**

`frontend/src/api/schemas.ts`:
```typescript
export const chatPreviewResponseSchema = z.object({
  context_block: z.string(),
  conversation: z.array(chatMessageSchema),
  llm_context: chatLlmContextMetaSchema.nullable().optional(),
})
export type ChatPreviewResponse = z.infer<typeof chatPreviewResponseSchema>
export function parseChatPreviewResponse(raw: unknown): ChatPreviewResponse {
  return chatPreviewResponseSchema.parse(raw)
}
```

**Step 4: Run test to verify it passes**

Run: `npm test -- -t "chatPreviewResponse"`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/api/schemas.ts frontend/src/api/schemas.test.ts
git commit -m "feat(ui): add frontend schemas for chat preview"
```

### Task 4: Frontend UI - Preview Modal

**Files:**
- Modify: `frontend/src/panels/chat/ChatPanel.tsx`
- Modify: `frontend/src/panels/chat/ChatPanel.test.tsx`
- Modify: `frontend/src/App.css` または対応するCSSファイル

**Step 1: Write the failing test**

`ChatPanel.test.tsx` で「プレビューボタンをクリックするとAPIリクエストが飛び、モーダル内にコンテキストが表示されること」を検証するテストを追加。

**Step 2: Run test to verify it fails**

Run: `npm test -- -t "preview modal"`
Expected: FAIL

**Step 3: Write minimal implementation**

- `ChatPanel.tsx` に状態変数 `previewData` と `isPreviewLoading`, `showPreviewModal` などを追加。
- 「プレビュー」ボタンを追加し、クリック時に `/api/chat/preview` へ POST。
- API戻り値をモーダル風（あるいは `<dialog>` 要素）で画面に表示するUIを追加。

**Step 4: Run test to verify it passes**

Run: `npm test -- ChatPanel.test.tsx`
Expected: PASS

**Step 5: Commit**

```bash
git add frontend/src/panels/chat/ChatPanel.tsx frontend/src/panels/chat/ChatPanel.test.tsx frontend/src/App.css
git commit -m "feat(ui): implement chat prompt preview Modal"
```
