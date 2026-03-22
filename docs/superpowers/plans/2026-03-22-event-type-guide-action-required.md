# 種別ガイド「対処要否」＋一覧強調 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `event_type_guides` に **対処が必要か** を明示するフラグ（`action_required`）を追加し、イベント一覧・概要の要注意イベント表で **該当行を視覚的に強調**する。判定はテキストの空欄ではなく **このフラグのみ**とする。

**Architecture:** DB に `BOOLEAN NOT NULL DEFAULT false` を追加。`EventTypeGuideSnippet` と CRUD スキーマに同フィールドを載せる。`GET /api/events` と `GET /api/dashboard/summary` の `EventRead.type_guide` 付与ロジックを **1 か所に集約**（例: `attach_type_guides_to_event_reads` ヘルパー）し、`dashboard` と `events` の両方から呼ぶ。フロントは `type_guide.action_required === true` の行に CSS クラスを付与する。

**Tech Stack:** Alembic / SQLAlchemy / FastAPI / Pydantic v2 / React / Zod / 既存の [`EventTypeGuide`](src/vcenter_event_assistant/db/models.py) 周辺

---

## スコープ外（YAGNI）

- 種別ガイドの JSON インポート／エクスポートへの `action_required` 連携（将来スコアルールと同様に拡張する場合は別タスク）
- CSV エクスポートへの列追加

---

## ファイル構成

| 役割 | パス |
|------|------|
| マイグレーション | 新規 `alembic/versions/<revision>_add_event_type_guide_action_required.py`（`down_revision`: 現在 head = `b2c3d4e5f6a7`） |
| ORM | 変更 [`src/vcenter_event_assistant/db/models.py`](src/vcenter_event_assistant/db/models.py) `EventTypeGuide` |
| スキーマ | 変更 [`src/vcenter_event_assistant/api/schemas.py`](src/vcenter_event_assistant/api/schemas.py)（`EventTypeGuideSnippet`, Create/Update/Read） |
| ガイド付与の共通化 | **新規** `src/vcenter_event_assistant/services/event_type_guide_attach.py`（または `api/event_type_guide_attach.py`）— `EventRecord` 列と `dict[str, EventTypeGuide]` から `EventRead` を組み立て |
| イベント一覧 | 変更 [`src/vcenter_event_assistant/api/routes/events.py`](src/vcenter_event_assistant/api/routes/events.py) — ヘルパー利用 |
| ダッシュボード | 変更 [`src/vcenter_event_assistant/api/routes/dashboard.py`](src/vcenter_event_assistant/api/routes/dashboard.py) — `top_notable_events` に `type_guide`（`action_required` 含む）を付与 |
| CRUD | 変更 [`src/vcenter_event_assistant/api/routes/event_type_guides.py`](src/vcenter_event_assistant/api/routes/event_type_guides.py) — create で `action_required` 既定 `False` |
| テスト | 変更 [`tests/test_event_type_guides_api.py`](tests/test_event_type_guides_api.py)、新規または変更 `tests/test_dashboard_summary.py`、変更 [`tests/test_events_list.py`](tests/test_events_list.py) |
| Zod | 変更 [`frontend/src/api/schemas.ts`](frontend/src/api/schemas.ts) |
| 設定 UI | 変更 [`frontend/src/panels/settings/EventTypeGuidesPanel.tsx`](frontend/src/panels/settings/EventTypeGuidesPanel.tsx) — チェックボックス「対処が必要」 |
| イベント一覧 UI | 変更 [`frontend/src/panels/events/EventsPanel.tsx`](frontend/src/panels/events/EventsPanel.tsx) — `<tr>` に条件付きクラス |
| 概要 UI | 変更 [`frontend/src/panels/summary/SummaryPanel.tsx`](frontend/src/panels/summary/SummaryPanel.tsx) — 同上 + ガイド列は任意（下記 Task 参照） |
| スタイル | 変更 [`frontend/src/App.css`](frontend/src/App.css) — 強調行（背景・左ボーダー。テーマ変数のみ。`style` での固定色禁止） |

---

## Task 1: DB とモデル

**Files:** 新規 Alembic、[`models.py`](src/vcenter_event_assistant/db/models.py)

- [ ] **Step 1:** Alembic で `event_type_guides.action_required` を追加  
  - 型: `Boolean`、**NOT NULL**、`server_default` / `default` は **false**（既存行はすべて「対処不要」扱いで開始）

- [ ] **Step 2:** `EventTypeGuide` に `action_required: Mapped[bool]` を追加

- [ ] **Step 3:** `uv run alembic upgrade head`（ローカル DB で確認。`create_all` のみの環境はマイグレーションと二重定義に注意）

---

## Task 2: Pydantic と CRUD

**Files:** [`schemas.py`](src/vcenter_event_assistant/api/schemas.py)、[`event_type_guides.py`](src/vcenter_event_assistant/api/routes/event_type_guides.py)

- [ ] **Step 1:** `EventTypeGuideSnippet` に `action_required: bool = False`

- [ ] **Step 2:** `EventTypeGuideCreate` に `action_required: bool = False`（省略時は false）

- [ ] **Step 3:** `EventTypeGuideUpdate` に `action_required: bool | None = None`（PATCH で `exclude_unset` により部分更新可）

- [ ] **Step 4:** `EventTypeGuideRead` に `action_required: bool`

- [ ] **Step 5:** `create_event_type_guide` で `EventTypeGuide(..., action_required=body.action_required)` を渡す

- [ ] **Step 6:** 失敗テストを追加してから実装（TDD 推奨）  
  例: `POST` で `action_required: true` が JSON で返る

```python
# tests/test_event_type_guides_api.py に追加する例
async def test_create_event_type_guide_action_required(client: AsyncClient) -> None:
    r = await client.post(
        "/api/event-type-guides",
        json={
            "event_type": "vim.event.Foo",
            "action_required": True,
            "general_meaning": "x",
        },
    )
    assert r.status_code == 201
    assert r.json()["action_required"] is True
```

- [ ] **Step 7:** `uv run pytest tests/test_event_type_guides_api.py -v`

---

## Task 3: ガイド付与の共通化と API 2 箇所

**Files:** 新規ヘルパーモジュール、[`events.py`](src/vcenter_event_assistant/api/routes/events.py)、[`dashboard.py`](src/vcenter_event_assistant/api/routes/dashboard.py)

- [ ] **Step 1:** ヘルパー（例）を実装する  
  - 入力: `AsyncSession`、`list[EventRecord]`  
  - 処理: `event_type` の集合で `EventTypeGuide` を `IN` クエリ、各行を `EventRead` + `EventTypeGuideSnippet(general_meaning=..., typical_causes=..., remediation=..., action_required=guide.action_required)` にマージ  
  - ガイドなし: `type_guide` は `None`（現状と同様）

- [ ] **Step 2:** `list_events` 内のインライン `_with_guide` をヘルパー呼び出しに置換

- [ ] **Step 3:** `dashboard_summary` の `top_notable_events=[EventRead.model_validate(e) for e in top]` を、**同じヘルパー**で `type_guide` 付きのリストに変更

- [ ] **Step 4:** テスト  
  - [`tests/test_events_list.py`](tests/test_events_list.py): `action_required` が `type_guide` に載ることをアサート  
  - [`tests/test_dashboard_summary.py`](tests/test_dashboard_summary.py): `top_notable_events` の要素に `type_guide` が付くケース（ガイド登録＋イベント投入）を追加

```bash
uv run pytest tests/test_events_list.py tests/test_dashboard_summary.py tests/test_event_type_guides_api.py -v
```

---

## Task 4: フロント — Zod と種別ガイド設定

**Files:** [`frontend/src/api/schemas.ts`](frontend/src/api/schemas.ts)、[`EventTypeGuidesPanel.tsx`](frontend/src/panels/settings/EventTypeGuidesPanel.tsx)

- [ ] **Step 1:** `eventTypeGuideSnippetSchema` に `action_required: z.boolean().optional()`（API は常に bool を返すなら `.default(false)` も可）

- [ ] **Step 2:** `eventTypeGuideRowSchema` に `action_required: z.boolean()`

- [ ] **Step 3:** `EventTypeGuidesPanel` の `Draft` に `action_required: boolean`、追加フォームにチェック「対処が必要」、一覧行にチェック、保存／追加時に API へ送信

---

## Task 5: フロント — 一覧行の強調

**Files:** [`EventsPanel.tsx`](frontend/src/panels/events/EventsPanel.tsx)、[`SummaryPanel.tsx`](frontend/src/panels/summary/SummaryPanel.tsx)、[`App.css`](frontend/src/App.css)

- [ ] **Step 1:** 強調条件を関数化（例: `function shouldHighlightGuideRow(g: EventTypeGuideSnippet | null | undefined): boolean`）

```typescript
export function shouldHighlightEventRowForAction(
  typeGuide: EventTypeGuideSnippet | null | undefined,
): boolean {
  return typeGuide?.action_required === true
}
```

配置: `frontend/src/events/eventTypeGuideHighlight.ts` など小さなモジュール（`EventsPanel` / `SummaryPanel` から import）

- [ ] **Step 2:** `EventsPanel` の `<tr>` に `className` を結合（強調時は `event-row--action-required` など）

- [ ] **Step 3:** `SummaryPanel` の要注意イベント表の `<tr>` に同じクラスを付与（`parseSummary` 後の `EventRow` に `type_guide` が載ることを前提）

- [ ] **Step 4:** `App.css` で `.event-row--action-required`（薄い背景 + 左アクセント。既存の `--color-*` / `--spacing-*` を使用）

- [ ] **Step 5:** ガイド列の `summary` 文言（例:「表示」）は任意で「要対処」表示に差し替え可能だが、**YAGNI なら行強調のみ**で十分

---

## Task 6: 検証

- [ ] **Step 1:** `uv run pytest` 全件

- [ ] **Step 2:** `cd frontend && npm test -- --run && npm run build`

- [ ] **Step 3:** 手動: 種別ガイドで「対処が必要」を ON → 該当種別のイベントが概要・イベントの両表で強調されること

- [ ] **Step 4:** Conventional Commits でコミット（例: `feat: add action_required to event type guides`）

---

## 計画レビュー

可能なら `plan-document-reviewer` でプラン本文をレビュー（実装前）。

---

## 実行の選び方

プラン承認後:

1. **Subagent-Driven（推奨）** — タスクごとにサブエージェント + レビュー  
2. **Inline Execution** — 同一セッションで `executing-plans` に沿って一括実行  

どちらで進めるか指定してください。
