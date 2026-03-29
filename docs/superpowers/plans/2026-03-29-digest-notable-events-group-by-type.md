# ダイジェスト「要注意イベント」種別集約 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一 `event_type` の要注意イベントを Markdown ダイジェスト上で **1 エントリに集約**し、件数・発生時刻レンジ・代表メッセージを表示する（LLM 入力 JSON の重複も削減する）。

**Architecture:** `build_digest_context` は現状 `notable_score` 降順で **行ベース TOP N** を取得しているため、週次で同一失敗が日次で繰り返すと列挙される。十分な行を取得したあと **Python で `event_type` ごとにバケット化**し、グループ単位でソート・上限適用する。純粋関数に集約ロジックを切り出し、単体テストで TDD する。

**Tech Stack:** Python 3.12、Pydantic v2、SQLAlchemy 2.0 async、pytest、Jinja2（[`digest.md.j2`](../../../src/vcenter_event_assistant/templates/digest.md.j2)）

---

## ファイル構成（変更の境界）

| ファイル | 役割 |
|----------|------|
| [`src/vcenter_event_assistant/services/digest_context.py`](../../../src/vcenter_event_assistant/services/digest_context.py) | 新モデル `DigestNotableEventGroup`、定数、取得 `limit` 拡大、`_group_top_notable_by_event_type`（純関数）、`DigestContext` のフィールド置換 |
| [`src/vcenter_event_assistant/templates/digest.md.j2`](../../../src/vcenter_event_assistant/templates/digest.md.j2) | 「要注意イベント」セクションをグループ向けに変更 |
| [`tests/test_digest_context.py`](../../../tests/test_digest_context.py) | DB 統合: 同一種別複数行 → 1 グループ |
| [`tests/test_digest_notable_grouping.py`](../../../tests/test_digest_notable_grouping.py) | **新規**: 純関数の単体テスト（DB なし） |
| [`tests/test_digest_markdown.py`](../../../tests/test_digest_markdown.py) | `DigestContext` フィクスチャを `top_notable_event_groups` に更新 |
| [`tests/test_digest_llm.py`](../../../tests/test_digest_llm.py) | 空 `DigestContext` フィクスチャのフィールド名追随 |
| [`docs/development.md`](../../../docs/development.md) | 「件数の上限」節の `top_notable_events` 記述をグループ前提に更新 |

**変更しないもの:** [`src/vcenter_event_assistant/api/routes/dashboard.py`](../../../src/vcenter_event_assistant/api/routes/dashboard.py) の `top_notable_events`（ダッシュボード用。`DigestContext` とは別）。

**カスタムテンプレ利用者:** `DIGEST_TEMPLATE_*` で `ctx.top_notable_events` を参照している場合は **破壊的変更**。`.env.example` の Batch digest 近辺に 1 行で「テンプレの `top_notable_event_groups` へ移行」と書く（必要なら）。

---

## データモデル（確定仕様）

`DigestNotableEventGroup`（名前は実装で統一）:

- `event_type: str`
- `occurrence_count: int`（当該種別・期間・`top_notable_min_score` 以上）
- `notable_score: int`（グループ内 **max**）
- `occurred_at_first: datetime` / `occurred_at_last: datetime`（timezone-aware）
- `entity_name: str | None` — グループ内で **全行同一ならその値**、異なれば `None`（テンプレで「複数エンティティ」等と表記可能）
- `message: str` — **代表**（`occurred_at` **最新**の行の `message`、長さ切り詰めはテンプレ側で既存どおり `[:200]` 可）

`DigestContext` は `top_notable_events: list[DigestContextEventSnippet]` を **`top_notable_event_groups: list[DigestNotableEventGroup]` に置換**（後方互換で旧フィールドを残さない）。

定数案:

- `_TOP_NOTABLE_RAW_FETCH_LIMIT = 200`（バケット前に読む行の上限）
- `_TOP_NOTABLE_EVENT_GROUPS_LIMIT = 10`（出力グループ数の上限）

ソート: グループを `notable_score desc`、`occurred_at_last desc`、`event_type` で安定化。

---

### Task 1: 純関数の失敗テスト（TDD RED）

**Files:**

- Create: [`tests/test_digest_notable_grouping.py`](../../../tests/test_digest_notable_grouping.py)
- Modify: （まだ無し — 次タスクで関数を `digest_context` に追加）

- [ ] **Step 1: 失敗するテストを書く**

同一 `event_type` が 3 件（時刻のみ異なる）→ **1 グループ**、`occurrence_count == 3`、`occurred_at_first` / `occurred_at_last` が min/max、`notable_score` は max、代表 `message` は **最新時刻**の行。

```python
def test_group_top_notable_by_event_type_merges_same_type() -> None:
    from vcenter_event_assistant.services.digest_context import group_notable_rows_by_event_type
    from vcenter_event_assistant.services.digest_context import DigestContextEventSnippet  # または Row 用の軽い型

    vid = uuid.uuid4()
    t0 = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    rows = [
        _snippet(..., occurred_at=t0, event_type="A", notable_score=15, message="m"),
        _snippet(..., occurred_at=t0 + timedelta(days=1), event_type="A", notable_score=15, message="m"),
        _snippet(..., occurred_at=t0 + timedelta(days=2), event_type="A", notable_score=15, message="m"),
    ]
    groups = group_notable_rows_by_event_type(rows)
    assert len(groups) == 1
    g = groups[0]
    assert g.event_type == "A"
    assert g.occurrence_count == 3
    assert g.occurred_at_first == t0
    assert g.occurred_at_last == t0 + timedelta(days=2)
    assert g.notable_score == 15
    assert g.message == "m"  # 最新行に合わせる
```

別テスト: 種別 `A` と `B` → **2 グループ**、ソートでスコア高い方が先。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/test_digest_notable_grouping.py -v --override-ini addopts=`

Expected: `ImportError` または `AttributeError`（関数未実装）

---

### Task 2: 純関数の実装（TDD GREEN）

**Files:**

- Modify: [`src/vcenter_event_assistant/services/digest_context.py`](../../../src/vcenter_event_assistant/services/digest_context.py)（`DigestNotableEventGroup` モデル、`group_notable_rows_by_event_type` 公開関数またはモジュールレベル関数）

- [ ] **Step 3: 最小実装**

- `DigestContextEventSnippet` のリストを受け取り、辞書で `event_type` ごとに集約。
- [ ] **Step 4: pytest で GREEN**

Run: `uv run pytest tests/test_digest_notable_grouping.py -v --override-ini addopts=`

- [ ] **Step 5: Commit**

```bash
git add tests/test_digest_notable_grouping.py src/vcenter_event_assistant/services/digest_context.py
git commit -m "feat(digest): group notable events by event_type (pure function)"
```

---

### Task 3: `build_digest_context` 統合と `DigestContext` 破壊的変更

**Files:**

- Modify: [`src/vcenter_event_assistant/services/digest_context.py`](../../../src/vcenter_event_assistant/services/digest_context.py)

- [ ] **Step 1: `DigestContext` を `top_notable_event_groups` に変更**（Pydantic モデル更新）。
- [ ] **Step 2:** `top_q` の `.limit(_TOP_NOTABLE_EVENTS_LIMIT)` を **`_TOP_NOTABLE_RAW_FETCH_LIMIT`** に変更。`top_rows` → `group_notable_rows_by_event_type` → **先頭 `_TOP_NOTABLE_EVENT_GROUPS_LIMIT` 件**を `DigestContext` に載せる。
- [ ] **Step 3:** [`tests/test_digest_context.py`](../../../tests/test_digest_context.py) を更新: 既存 `test_build_digest_context_counts_and_top_rows` は `top_notable_event_groups[0]` をアサート。**新規** `test_build_digest_context_groups_same_event_type`: 同一種別を 3 行投入 → `len(groups)==1` かつ `occurrence_count==3`。

Run: `uv run pytest tests/test_digest_context.py -v --override-ini addopts=`

- [ ] **Step 4: Commit**

---

### Task 4: Jinja テンプレと Markdown テスト

**Files:**

- Modify: [`src/vcenter_event_assistant/templates/digest.md.j2`](../../../src/vcenter_event_assistant/templates/digest.md.j2)
- Modify: [`tests/test_digest_markdown.py`](../../../tests/test_digest_markdown.py)

- [ ] **Step 1:** テンプレで `{% for g in ctx.top_notable_event_groups[:20] %}` とし、1 行に `event_type` / `occurrence_count` / `notable_score` / 時刻レンジ / `entity_name` / `message` を日本語で読みやすく記載（例: 「7 回、2026-03-22 … 2026-03-28」）。
- [ ] **Step 2:** `test_render_digest_markdown_uses_kind_not_title` 等の `DigestContext(...)` を新フィールドに差し替え。代表テストで「要注意」セクションに `occurrence_count` または「回」が含まれることを **1 件**アサート追加してもよい。

Run: `uv run pytest tests/test_digest_markdown.py -v --override-ini addopts=`

- [ ] **Step 3: Commit**

---

### Task 5: 残りテスト・LLM・ドキュメント

**Files:**

- Modify: [`tests/test_digest_llm.py`](../../../tests/test_digest_llm.py)
- Modify: [`docs/development.md`](../../../docs/development.md)
- Modify: [`.env.example`](../../../.env.example)（任意: テンプレ破壊的変更の一行注記）

- [ ] **Step 1:** `_minimal_ctx()` の `top_notable_events=[]` → `top_notable_event_groups=[]`
- [ ] **Step 2:** `docs/development.md` の「件数の上限」で `top_notable_events` と「最大 10 件」を **グループ数・取得行上限**に合わせて修正
- [ ] **Step 3:** 広域回帰 `uv run pytest --override-ini addopts=`（時間がかかる場合は digest 関連に限定）

Run: `uv run pytest tests/test_digest_llm.py tests/test_digest_context.py tests/test_digest_markdown.py tests/test_digest_notable_grouping.py -v --override-ini addopts=`

- [ ] **Step 4: Commit**

```bash
git commit -m "docs: digest notable groups and template migration note"
```

---

## Plan review loop

1. 本計画と（存在すれば）[`docs/superpowers/specs/`](../../specs/) の digest 関連 spec を **plan-document-reviewer** に渡しレビュー。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。

---

## Execution handoff

**Plan complete and saved to [`docs/superpowers/plans/2026-03-29-digest-notable-events-group-by-type.md`](./2026-03-29-digest-notable-events-group-by-type.md). Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新規サブエージェントを dispatch（@superpowers:subagent-driven-development）
2. **Inline Execution** — 同一セッションで @superpowers:executing-plans に従いチェックポイント付きで実装

**Which approach?**
