# チャット WEB 検索条件のユーザー指定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings「チャット」で WEB 検索のスコープ・積極度を永続化し、許可 ON 時にサーバがプロンプト/ツール説明を切り替える。

**Architecture:** localStorage prefs → ChatRequest enum フィールド → `compose_chat_system_prompt` / `web_search_tool_description(scope)` でソフトゲート文言を組み立て。ハードゲート（オプトイン・sanitize・max calls）は不変。

**Tech Stack:** FastAPI/Pydantic, React/Zod, localStorage prefs（既存 Provider パターン）

**Spec:** `docs/superpowers/specs/2026-07-29-chat-web-search-prefs-design.md`

## Global Constraints

- 既定: `web_search_scope=vmware_ecosystem`, `web_search_aggressiveness=balanced`
- 入力欄「WEB 検索を許可」は都度・非永続のまま
- `enable_web_search=false` またはプロバイダ未構成時は prefs フィールド無視
- ツール説明は scope のみ、積極度はシステム指針のみ
- localStorage キー: `vea.chat_web_search_prefs`

---

### Task 1: Backend — enum・プロンプト/ツール説明の切替

**Files:**
- Modify: `src/vcenter_event_assistant/api/schemas/chat.py`
- Modify: `src/vcenter_event_assistant/services/chat/chat_llm_payload.py`
- Modify: `src/vcenter_event_assistant/services/chat/chat_web_search.py`
- Modify: `src/vcenter_event_assistant/services/chat/chat_llm.py`
- Modify: `src/vcenter_event_assistant/api/routes/chat.py`
- Test: `tests/services/chat/test_chat_llm_payload.py`, `tests/services/chat/test_chat_llm.py`, `tests/services/chat/test_chat_web_search.py`, `tests/test_chat_api.py`

**Interfaces:**
- Produces:
  - `WebSearchScope = Literal["incidents", "vsphere_ops", "vmware_ecosystem"]`
  - `WebSearchAggressiveness = Literal["conservative", "balanced", "aggressive"]`
  - `ChatRequest.web_search_scope` / `web_search_aggressiveness` (optional, defaults as above)
  - `compose_chat_system_prompt(*, enable_web_search: bool, scope: WebSearchScope = "vmware_ecosystem", aggressiveness: WebSearchAggressiveness = "balanced") -> str`
  - `web_search_tool_description(scope: WebSearchScope) -> str`
  - `run_period_chat(..., web_search_scope=..., web_search_aggressiveness=...)`

- [ ] **Step 1: RED — payload テスト**

`compose_chat_system_prompt` が scope/aggressiveness で文言を変え、`enable_web_search=False` では指針なしであることを断言するテストを追加。`web_search_tool_description` も scope ごとに異なることを断言。

- [ ] **Step 2: GREEN — 文言テーブルと compose / tool description**

`chat_llm_payload.py` にスコープ別対象文言・積極度別指針テーブルを置き、`CHAT_WEB_SEARCH_GUIDANCE` を balanced+vmware_ecosystem 相当の組み立て結果に置き換え（後方互換エイリアス可）。

`chat_web_search.py`: `web_search` の固定 docstring は generic なままでもよいが、`bind_tools` / Copilot `define_tool` には `web_search_tool_description(scope)` を渡す。実行時に scope を渡せるよう `run_chat_with_web_search` / `build_copilot_web_search_tool` / `run_copilot_chat_with_web_search` に `scope` 引数を追加。

- [ ] **Step 3: ChatRequest + route + run_period_chat**

スキーマ追加、`routes/chat.py` から渡し、`run_period_chat` で provider ありのときだけ `compose_chat_system_prompt(..., scope=..., aggressiveness=...)` とツール説明に反映。

- [ ] **Step 4: API/LLM テスト更新・実行**

```bash
uv run pytest tests/services/chat/test_chat_llm_payload.py tests/services/chat/test_chat_llm.py tests/services/chat/test_chat_web_search.py tests/test_chat_api.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/api/schemas/chat.py src/vcenter_event_assistant/api/routes/chat.py src/vcenter_event_assistant/services/chat/ tests/services/chat/ tests/test_chat_api.py
git commit -m "feat(chat): WEB 検索の scope/aggressiveness でプロンプトを切替"
```

---

### Task 2: Frontend — prefs storage / Provider / Settings UI / 送信

**Files:**
- Create: `frontend/src/preferences/chatWebSearchPrefsStorage.ts`
- Create: `frontend/src/preferences/chatWebSearchPrefsStorage.test.ts`
- Create: `frontend/src/preferences/chatWebSearchPrefsContext.ts`
- Create: `frontend/src/preferences/ChatWebSearchPrefsProvider.tsx`
- Create: `frontend/src/preferences/useChatWebSearchPrefs.ts`
- Create: `frontend/src/panels/settings/ChatWebSearchPrefsPanel.tsx`
- Create: `frontend/src/panels/settings/ChatWebSearchPrefsPanel.test.tsx`（任意・最小）
- Modify: `frontend/src/components/AppProviders.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api/schemas/chat.ts`
- Modify: `frontend/src/hooks/useChatPanelController.ts`
- Modify: `frontend/src/panels/chat/ChatPanel.test.tsx`（body 送信の期待を更新）
- Test: storage / panel / ChatPanel 送信

**Interfaces:**
- Produces:
  - `ChatWebSearchPrefs = { scope: ..., aggressiveness: ... }`
  - `DEFAULT_CHAT_WEB_SEARCH_PREFS`
  - `readStoredChatWebSearchPrefs()` / `writeStoredChatWebSearchPrefs(prefs)`
  - `useChatWebSearchPrefs(): { prefs, setPrefs }`

- [ ] **Step 1: RED — storage テスト**（正常・不正 JSON・未知 enum → 既定）

- [ ] **Step 2: GREEN — storage + Provider + hook**

- [ ] **Step 3: Settings UI** — `ChatWebSearchPrefsPanel` をサンプルの上に配置。`panelLabel` を「チャット設定」に。Zod にフィールド追加。`buildChatRequestBody` で `enable_web_search` 真のときだけ `web_search_scope` / `web_search_aggressiveness` を載せる。

- [ ] **Step 4: Frontend テスト**

```bash
cd frontend && npm test -- --run src/preferences/chatWebSearchPrefsStorage.test.ts src/panels/chat/ChatPanel.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Settings で WEB 検索条件を永続化し送信する"
```

---

### Task 3: Docs

**Files:**
- Modify: `docs/web-search-conditions.md`
- Modify: `docs/user-guides/chat.md`（設定 → チャット節）

- [ ] **Step 1: 経路 B にユーザー指定条件を追記。user-guide にセレクト 2 つの説明を短く追加。**

- [ ] **Step 2: Commit**

```bash
git add docs/web-search-conditions.md docs/user-guides/chat.md
git commit -m "docs: WEB 検索条件のユーザー指定を記載"
```

---

## Spec coverage check

| Spec 項目 | Task |
|-----------|------|
| P-1〜P-7 判断 | 全体 |
| UI セレクト・補足文 | Task 2 |
| localStorage | Task 2 |
| API enum・省略時既定 | Task 1 |
| compose / tool description | Task 1 |
| docs | Task 3 |
| 非目標（トグル永続化等） | 触れない |
