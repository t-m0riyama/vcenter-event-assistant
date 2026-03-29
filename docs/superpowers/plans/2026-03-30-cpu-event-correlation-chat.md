# CPU–イベント時刻近接コンテキスト（チャット専用）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: **`@superpowers:subagent-driven-development`**（推奨）または **`@superpowers:executing-plans`**。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** **`@superpowers:test-driven-development`** を厳守する。各タスクで **失敗するテストを先に書く → RED 確認 → 最小実装 → GREEN → リファクタ**。本番コードをテストより先に書かない。

**Goal:** `POST /api/chat` で **オプトイン**したときだけ、高 CPU サンプル時刻をアンカーに **± 時間窓内のイベント**をホスト名で突き合わせた集約を JSON に載せ、LLM が「高負荷時に多いイベント」等に答えられるようにする。**バッチダイジェスト**（`run_digest_once` / `build_digest_context` / `augment_digest_with_llm`）には **追加クエリを入れず負荷を増やさない**。

**Architecture:** 相関集計は新モジュール（例: `correlation_context.py`）の `build_cpu_event_correlation` が **SQLite/Postgres 共通の SQLAlchemy** で `MetricSample`（`host.cpu.usage_pct`）と `EventRecord` を期間・`vcenter_id` で絞り込む。`DigestContext` 本体は変更せず、`run_period_chat` に **任意の第 2 ブロック**（Pydantic モデル）を渡し、ユーザ向け JSON は `{"digest_context": ..., "cpu_event_correlation": ... | null}` を `_trim_context_json` 相当で連結・トリムする。ホスト突き合わせは **MVP は `EventRecord.entity_name` とメトリクス行の `entity_name` の一致**（イベントに `entity_moid` が無いため。将来の moid 保存は別タスク）。

**Tech Stack:** Python 3.12、Pydantic v2、SQLAlchemy 2.0 async、pytest、既存 [`chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) / [`digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) の `_trim_context_json` パターン。

**関連:** 設計メモ [`.cursor/plans/llm相関コンテキスト設計_615860dd.plan.md`](../../../.cursor/plans/llm相関コンテキスト設計_615860dd.plan.md)（ダイジェスト低負荷の制約）。

---

## ファイル構成（変更の境界）

| ファイル | 責務 |
| -------- | ---- |
| [`src/vcenter_event_assistant/services/correlation_context.py`](../../src/vcenter_event_assistant/services/correlation_context.py) | **新規。** Pydantic モデル（`CpuEventCorrelationPayload` 等）、`build_cpu_event_correlation(session, from_utc, to_utc, *, vcenter_id, threshold_pct, window_minutes, max_anchors)`。 |
| [`tests/test_correlation_context.py`](../../tests/test_correlation_context.py) | **新規。** メモリ DB に `MetricSample` / `EventRecord` / `VCenter` を投入し、窓内イベントが集計されることの統合テスト。 |
| [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py) | `ChatRequest` に `include_cpu_event_correlation: bool = False` および任意 `cpu_correlation_threshold_pct` / `cpu_correlation_window_minutes`（上限・デフォルトは Field で固定）。 |
| [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py) | `include_cpu_event_correlation` が真のときだけ `build_cpu_event_correlation` を await。`run_period_chat` に `correlation` を渡す。 |
| [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | `run_period_chat(..., correlation: CpuEventCorrelationPayload | None = None)`。JSON は `digest_context` + 任意 `cpu_event_correlation` をマージして1ユーザーブロック化。`_CHAT_SYSTEM_PROMPT` に「近接集計であり因果断定ではない」一文。 |
| [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py) | `correlation` あり時にマージ JSON にキーが含まれること（モック HTTP は既存どおり）。 |
| [`tests/test_chat_api.py`](../../tests/test_chat_api.py) | `include_cpu_event_correlation: true` で相関ビルダが呼ばれることを `patch` で検証（または DB フィクスチャで 200）。 |
| [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts) | Zod にフィールド追加。 |
| [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx) | チェックボックス「CPU 高負荷とイベントの近接集約を含める（負荷あり）」等。 |
| [`docs/development.md`](../../docs/development.md) | `/api/chat` のオプションとダイジェスト非対象を1段落。 |

**変更しないもの:** [`src/vcenter_event_assistant/services/digest_run.py`](../../src/vcenter_event_assistant/services/digest_run.py)、[`digest_llm.py`](../../src/vcenter_event_assistant/services/digest_llm.py) のダイジェスト経路、`build_digest_context` のシグネチャ（既存チャット互換のためデフォルトのまま）。

---

### Task 1: `build_cpu_event_correlation` と DB 統合テスト（TDD）

**Files:**

- Create: [`src/vcenter_event_assistant/services/correlation_context.py`](../../src/vcenter_event_assistant/services/correlation_context.py)
- Create: [`tests/test_correlation_context.py`](../../tests/test_correlation_context.py)

**契約（MVP）:**

- 入力: `from_utc < to_utc`、`vcenter_id` 任意、`threshold_pct`（例: 85）、`window_minutes`（例: 15）、`max_anchors`（例: 20）。
- CPU サンプル: `metric_key == "host.cpu.usage_pct"`、`value >= threshold`、`sampled_at` が期間内。`value` 降順で上位 `max_anchors` 件をアンカー（同一 `entity_moid` の重複は **1 アンカーにマージ**するなど簡略化可）。
- 各アンカーについて、イベントは `occurred_at` が `[sampled_at - window, sampled_at + window]`（UTC）かつ `EventRecord.entity_name == MetricSample.entity_name`（ホスト名一致）。
- 出力: アンカーごとに `event_type` ごとの件数、代表 `occurred_at` など、トークン節約の構造（リストは上限付き）。

- [ ] **Step 1: 失敗するテストを書く**

`test_correlation_context.py` に `test_build_cpu_event_correlation_counts_events_in_window` を追加: 1 ホスト・1 件 CPU サンプル（閾値超え）・窓内に 2 イベント（同 `entity_name`）・窓外に 1 イベント → 窓内の 2 件のみカウント。

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/test_correlation_context.py -v --override-ini addopts=`

Expected: `ImportError` または `AssertionError`

- [ ] **Step 3: 最小実装**

`correlation_context.py` に Pydantic モデルと `build_cpu_event_correlation`。

- [ ] **Step 4: GREEN**

Run: `uv run pytest tests/test_correlation_context.py -v --override-ini addopts=`

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/correlation_context.py tests/test_correlation_context.py
git commit -m "feat(chat): CPU anchor window correlation aggregation"
```

---

### Task 2: `run_period_chat` が相関ペイロードをマージする（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)
- Modify: [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py)

- [ ] **Step 1: 失敗するテスト**

`test_chat_llm.py` に `test_run_period_chat_includes_correlation_key_in_user_block_when_set` を追加: `correlation=CpuEventCorrelationPayload(...)`（または最小 dict）を渡したとき、モックで capture した `messages[1]["content"]` に `"cpu_event_correlation"` 文字列（またはマージ後 JSON のキー）が含まれることを期待。**まだ引数が無い**なら RED。

- [ ] **Step 2: 実装**

`run_period_chat` に `correlation: CpuEventCorrelationPayload | None = None`。`context.model_dump` と `correlation.model_dump(mode="json")` を `{"digest_context": ..., "cpu_event_correlation": ...}` にし、`_context_user_block` を拡張するか専用関数 `_merged_context_block` で `_trim_context_json` に渡す（既存 80k 上限を踏襲）。

- [ ] **Step 3: GREEN**

Run: `uv run pytest tests/test_chat_llm.py -v --override-ini addopts=`

- [ ] **Step 4: Commit**

```bash
git add src/vcenter_event_assistant/services/chat_llm.py tests/test_chat_llm.py
git commit -m "feat(chat): merge optional CPU-event correlation into LLM context"
```

---

### Task 3: API スキーマと `POST /api/chat` 配線（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py)
- Modify: [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py)
- Modify: [`tests/test_chat_api.py`](../../tests/test_chat_api.py)

- [ ] **Step 1: 失敗するテスト**

`test_chat_api.py` に `test_post_chat_calls_correlation_when_flag_true` を追加: `unittest.mock.patch` で `build_cpu_event_correlation` をスパイし、`include_cpu_event_correlation: true` の POST で **1 回呼ばれる**こと。`false` のとき **0 回**。

- [ ] **Step 2: 実装**

`ChatRequest` にフラグと閾値・窓（デフォルト `false`）。`post_chat` でフラグが真のときだけ `build_cpu_event_correlation` を呼び、`run_period_chat(..., correlation=...)` に渡す。

- [ ] **Step 3: GREEN**

Run: `uv run pytest tests/test_chat_api.py -v --override-ini addopts=`

Run: `uv run pytest --override-ini addopts= -q`

- [ ] **Step 4: Commit**

```bash
git add src/vcenter_event_assistant/api/schemas.py src/vcenter_event_assistant/api/routes/chat.py tests/test_chat_api.py
git commit -m "feat(api): opt-in CPU-event correlation for chat"
```

---

### Task 4: フロント（オプトイン UI）

**Files:**

- Modify: [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts)
- Modify: [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)
- Modify: [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)

- [ ] **Step 1: 失敗するテスト**

`ChatPanel.test.tsx` でチェックをオンにした状態で送信 → `fetch` の body に `include_cpu_event_correlation: true` が含まれることを期待（**先にテスト追加で RED**）。

- [ ] **Step 2: 実装**

状態 `includeCorrelation` とチェックボックス。`apiPost` ボディに追加。

- [ ] **Step 3: GREEN**

Run: `npm test -- --run src/panels/chat/ChatPanel.test.tsx`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/schemas.ts frontend/src/panels/chat/
git commit -m "feat(ui): opt-in CPU-event correlation for chat"
```

---

### Task 5: ドキュメント

**Files:**

- Modify: [`docs/development.md`](../../docs/development.md)

- [ ] **Step 1:** 「期間コンテキスト付きチャット」節に、`include_cpu_event_correlation` と「ダイジェストには含めない」を追記。

- [ ] **Step 2: Commit**

```bash
git add docs/development.md
git commit -m "docs: chat CPU-event correlation option"
```

---

## Plan review loop

1. 本計画と（存在すれば）[`docs/superpowers/specs/`](../../specs/) を **plan-document-reviewer** に渡しレビュー。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。

---

## Execution handoff

**Plan complete and saved to [`docs/superpowers/plans/2026-03-30-cpu-event-correlation-chat.md`](./2026-03-30-cpu-event-correlation-chat.md). Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとに新規サブエージェントを dispatch（**`@superpowers:subagent-driven-development`**）
2. **Inline Execution** — 同一セッションで **`@superpowers:executing-plans`** に従いチェックポイント付きで実装

**Which approach?**
