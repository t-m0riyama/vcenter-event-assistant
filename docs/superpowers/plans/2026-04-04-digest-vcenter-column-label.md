# ダイジェスト・ダッシュボードの vCenter 列に表示名を載せる Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **実装時は superpowers:test-driven-development を遵守する**（本節「TDD」参照）。

**Goal:** `HighCpuHostRow` / `HighMemHostRow` の vCenter 列に、**接続ホスト（`VCenter.host`）ではなく、登録時の表示名（`VCenter.name`）** を出す。`name` が空のときのみ UUID 短縮（`str(id)[:8]…`）にフォールバックし、**`host` はこの列には使わない**（表示名と接続 FQDN の混同を防ぐ）。**登録表示名は LLM への記号化（匿名化）の対象に必ず含める**（外部 API に実名を送らない）。

**Architecture:** DB の `vcenters` を `MetricSample.vcenter_id` 集合で一括参照し、`id → 表示ラベル` の dict を組み立てて各行に付与する。ロジックは 1 箇所に集約（例: [`vcenter_labels.py`](../../src/vcenter_event_assistant/services/vcenter_labels.py) の `load_vcenter_labels_map`）。[`digest_context.build_digest_context`](../../src/vcenter_event_assistant/services/digest_context.py) と [`dashboard.py`](../../src/vcenter_event_assistant/api/routes/dashboard.py) の両方が同じ関数を呼ぶ。[`llm_anonymization.py`](../../src/vcenter_event_assistant/services/llm_anonymization.py) では **`vcenter_label` を `_COLLECT_KEYS` / `_ANONYMIZE_KEYS` に追加**し、集約 JSON 内の値を `token_for("vcenter", ...)` でトークン化する。テンプレート Markdown に同じ表示名文字列が表に出る場合、**収集フェーズでトークン登録済みの原文**として `anonymize_plain_text` により置換される（[`anonymize_for_llm`](../../src/vcenter_event_assistant/services/llm_anonymization.py) の流れと整合）。

**Tech Stack:** Python 3.12+、Pydantic v2、SQLAlchemy 2.0 async、pytest、Jinja2、既存フロント（Zod + React）。

**根拠:** 現状 [`digest.md.j2`](../../src/vcenter_event_assistant/templates/digest.md.j2) が `` `{{ h.vcenter_id[:8] }}…` `` のみを表示しているため、登録名があっても表に出ない。

## TDD（必須）

本計画の各タスクは **Red → Green → Refactor** で進める。**本番コードをテストより先に書かない**（スキルのアイロン則）。新しい振る舞いごとに次を満たすこと。

| 段階 | 内容 |
|------|------|
| **RED** | 振る舞い 1 つにつき、**先に**失敗するテストを追加する（明確なアサーション・本番コードに依存しない意図）。 |
| **Verify RED** | `uv run pytest path::test_name -v` を実行し、**意図どおり失敗**することを確認する（タイポや import エラーで失敗していないこと）。**スキップ不可。** |
| **GREEN** | テストを通すための**最小**実装だけ加える。タスク範囲外のリファクタや「ついで」機能は入れない。 |
| **Verify GREEN** | 対象テストと関連スイートが PASS することを確認する。 |
| **REFACTOR** | GREEN のあと、重複削除・名前整理のみ。振る舞いを変えない。 |

**例外:** 純粋な設定ファイルのみの変更など、スキルが許容するものは人間と合意してから。

**検証チェックリスト（完了前）:** 各新規・変更した公開関数／振る舞いにテストがあること。各テストについて **一度は RED を目視**したこと（実装後だけ追加したテストは、意図した失敗を見ていない可能性があるため、新規振る舞いでは必ず RED から始める）。

---

## ファイル一覧

| 操作 | パス |
|------|------|
| 新規 | `src/vcenter_event_assistant/services/vcenter_labels.py`（ラベル解決 + 一括読み込み） |
| 変更 | `src/vcenter_event_assistant/api/schemas.py`（`HighCpuHostRow` / `HighMemHostRow` に `vcenter_label`） |
| 変更 | `src/vcenter_event_assistant/services/digest_context.py` |
| 変更 | `src/vcenter_event_assistant/api/routes/dashboard.py` |
| 変更 | `src/vcenter_event_assistant/templates/digest.md.j2` |
| 変更 | `src/vcenter_event_assistant/services/llm_anonymization.py` |
| 変更 | `frontend/src/api/schemas.ts`（`summaryHostMetricRowSchema`） |
| 変更 | `frontend/src/panels/summary/SummaryPanel.tsx`（vCenter 列の追加） |
| テスト | `tests/test_vcenter_labels.py`（任意・純関数なら）、`tests/test_digest_context.py`、`tests/test_digest_markdown.py`、`tests/test_dashboard_summary.py` |
| 既存の `HighCpuHostRow` インスタンス生成箇所 | `tests/test_digest_markdown.py`、`tests/test_chat_llm.py`、`tests/test_digest_llm.py` など |

---

### Task 1: スキーマに `vcenter_label` を追加し、失敗するテストを書く（RED）

**Files:**
- 変更: [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py)
- 変更: [`tests/test_digest_context.py`](../../tests/test_digest_context.py)

- [ ] **Step 1: スキーマ変更**

[`HighCpuHostRow`](../../src/vcenter_event_assistant/api/schemas.py) と [`HighMemHostRow`](../../src/vcenter_event_assistant/api/schemas.py) に次を追加する。

```python
vcenter_label: str = Field(description="表示用（登録時の表示名 VCenter.name。空のときは vcenter_id 短縮。接続 host は使わない）")
```

`vcenter_id` は既存どおり残す（API 互換・デバッグ用）。

- [ ] **Step 2: 失敗するアサーションを追加（TDD）**

[`test_build_digest_context_counts_and_top_rows`](../../tests/test_digest_context.py) の末尾（`assert abs(ctx.high_cpu_hosts[0].value - 88.5) < 0.01` の直後）に次を足す。

```python
    assert ctx.high_cpu_hosts[0].vcenter_label == "ctx-vc"
```

同ファイルの [`test_build_digest_context_filters_by_vcenter_id`](../../tests/test_digest_context.py) の末尾に `assert ctx.high_cpu_hosts[0].vcenter_label == "vc-a"` を追加する（`vid_a` の `VCenter.name` が `"vc-a"` のため）。

- [ ] **Step 3: pytest で RED を確認**

```bash
cd /Users/moriyama/git/vcenter-event-assistant && uv run pytest tests/test_digest_context.py::test_build_digest_context_counts_and_top_rows -v
```

期待: `ValidationError` または `AttributeError` / `assert` 失敗（`vcenter_label` 未設定）。

- [ ] **Step 4: コミットはまだしない**（Task 2 で GREEN 後にまとめて可）

---

### Task 2: `vcenter_labels` モジュールと `build_digest_context` の実装（GREEN）

**Files:**
- 新規: `src/vcenter_event_assistant/services/vcenter_labels.py`
- 変更: `src/vcenter_event_assistant/services/digest_context.py`

- [ ] **Step 1: ラベル解決の純関数**

`vcenter_labels.py` に次を実装する（そのまま貼り付け可）。

```python
"""vCenter ID から表示ラベル（一覧表用）を解決する。"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import VCenter


def label_for_vcenter_row(v: VCenter) -> str:
    """登録時の表示名（name）のみ。空なら UUID 短縮。接続ホスト host は列に出さない。"""
    name = (v.name or "").strip()
    if name:
        return name
    return f"{str(v.id)[:8]}…"


def fallback_label_from_id(vcid: uuid.UUID) -> str:
    """vcenters に行が無いときのフォールバック。"""
    return f"{str(vcid)[:8]}…"


async def load_vcenter_labels_map(
    session: AsyncSession,
    ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """重複を除き vcenters から id → 表示ラベルを返す。欠損 id はフォールバック。"""
    unique = list({uid for uid in ids})
    if not unique:
        return {}
    rows = (await session.execute(select(VCenter).where(VCenter.id.in_(unique)))).scalars().all()
    by_id = {r.id: label_for_vcenter_row(r) for r in rows}
    out: dict[uuid.UUID, str] = {}
    for uid in unique:
        out[uid] = by_id.get(uid) or fallback_label_from_id(uid)
    return out
```

- [ ] **Step 2: `build_digest_context` で CPU / メモリ行に `vcenter_label` を設定**

`cpu_rows` / `mem_rows` を取得したあと:

```python
    ids_for_label = {r.vcenter_id for r in cpu_rows} | {r.vcenter_id for r in mem_rows}
    label_map = await load_vcenter_labels_map(session, ids_for_label)
```

`HighCpuHostRow(..., vcenter_label=label_map[r.vcenter_id])` のように渡す（`r.vcenter_id` は UUID）。

- [ ] **Step 3: GREEN 確認**

```bash
uv run pytest tests/test_digest_context.py -v
```

期待: 全て PASS。

- [ ] **Step 4: コミット**

```bash
git add src/vcenter_event_assistant/api/schemas.py src/vcenter_event_assistant/services/vcenter_labels.py src/vcenter_event_assistant/services/digest_context.py tests/test_digest_context.py
git commit -m "feat(digest): add vcenter_label to high_cpu/mem host rows"
```

---

### Task 3: ダッシュボード API とテスト

**Files:**
- 変更: [`src/vcenter_event_assistant/api/routes/dashboard.py`](../../src/vcenter_event_assistant/api/routes/dashboard.py)
- 変更: [`tests/test_dashboard_summary.py`](../../tests/test_dashboard_summary.py)

- [ ] **Step 1: RED — レスポンスに `vcenter_label` を期待するアサーション**

[`test_high_cpu_hosts_one_row_per_host_uses_peak_value`](../../tests/test_dashboard_summary.py) で、`same_host_rows[0]` に対し次を追加する。

```python
    assert same_host_rows[0]["vcenter_label"] == "dash-dedupe"
```

（`POST /api/vcenters` の `name` が `"dash-dedupe"` のため。）

メモリ用の類似テストがあれば同様に `vcenter_label` を検証する。

- [ ] **Step 2: GREEN — `dashboard.py` で `load_vcenter_labels_map` を利用**

`cpu_rows` / `mem_rows` 構築後、`HighCpuHostRow` / `HighMemHostRow` に `vcenter_label=label_map[uuid.UUID(r.vcenter_id)]` を渡す。`r.vcenter_id` が既に UUID 型ならそのままキーにする。

- [ ] **Step 3:**

```bash
uv run pytest tests/test_dashboard_summary.py -v
```

- [ ] **Step 4: コミット**

```bash
git commit -m "feat(dashboard): include vcenter_label in high_cpu/mem summary rows"
```

---

### Task 4: Jinja テンプレと Markdown レンダリングテスト

**Files:**
- 変更: [`src/vcenter_event_assistant/templates/digest.md.j2`](../../src/vcenter_event_assistant/templates/digest.md.j2)
- 変更: [`tests/test_digest_markdown.py`](../../tests/test_digest_markdown.py)

- [ ] **Step 1: テンプレ修正**

`digest.md.j2` の CPU / メモリ表の 2 行を、次のように置き換える。

```jinja
| `{{ h.vcenter_label }}` | `{{ h.entity_name }}` | {{ h.value|round(1) }} | `{{ h.sampled_at | fmt_ts }}` |
```

- [ ] **Step 2: RED — 既存の `HighCpuHostRow` コンストラクタが壊れる**

`test_digest_markdown.py` 内の `HighCpuHostRow` / `HighMemHostRow` 生成箇所に `vcenter_label="ラベルCPU"` / `vcenter_label="ラベルMEM"` を追加する。

[`test_render_digest_markdown_uses_kind_not_title`](../../tests/test_digest_markdown.py) の末尾付近に次を追加する。

```python
    assert "ラベルCPU" in md
    assert "ラベルMEM" in md
```

- [ ] **Step 3: GREEN**

```bash
uv run pytest tests/test_digest_markdown.py -v
```

- [ ] **Step 4: コミット**

---

### Task 5: LLM 記号化の対象に `vcenter_label` を追加（必須）

**Files:**
- 変更: [`src/vcenter_event_assistant/services/llm_anonymization.py`](../../src/vcenter_event_assistant/services/llm_anonymization.py)
- 変更: [`tests/test_llm_anonymization.py`](../../tests/test_llm_anonymization.py)
- 変更（任意・推奨）: [`tests/test_digest_llm.py`](../../tests/test_digest_llm.py) — ダイジェスト LLM 入力に表示名の原文が残らないことの 1 ケース

- [ ] **Step 1: RED**

`anonymize_json_like` に `{"high_cpu_hosts": [{"vcenter_label": "MyVC-Display", "entity_name": "h", ...}]}` のようなフラグメントを含む dict を渡し、出力に `MyVC-Display` が含まれないこと（および `deanonymize_text` で復元できること）を検証するテストを 1 本追加。

- [ ] **Step 2: GREEN**

次を実装する（漏れないこと）。

1. `_COLLECT_KEYS` に `("vcenter_label", "vcenter")` を追加（ツリー先に表示名を登録し、テンプレ本文の同文字列置換に使う）。
2. `_ANONYMIZE_KEYS` に `"vcenter_label"` を追加。
3. `_anonymize_node` で `k == "vcenter_label"` のとき `a.token_for("vcenter", v)` を使用（`entity_name` と同様の分岐を追加）。

- [ ] **Step 3:**

```bash
uv run pytest tests/test_llm_anonymization.py -v
```

- [ ] **Step 4（任意）:** `augment_digest_with_llm` のスパイで、`ctx` に `high_cpu_hosts` 用の表示名が含まれるケースを作り、`LLM_ANONYMIZATION_ENABLED` 相当がオン時、**HumanMessage にその表示名の原文が含まれない**ことを assert する（既存の [`test_augment_anonymizes_llm_input_but_keeps_template_body_in_output`](../../tests/test_digest_llm.py) を拡張するか、別テストを追加）。

---

### Task 6: その他テストの `HighCpuHostRow` / `DigestContext` 修正

**Files:**
- 変更: `tests/test_chat_llm.py`、`tests/test_digest_llm.py`、grep でヒットする他ファイル

- [ ] **Step 1: 検索**

```bash
rg "HighCpuHostRow\(|HighMemHostRow\(" tests src
```

- [ ] **Step 2:** 各インスタンスに `vcenter_label="dummy"` または文脈に合う文字列を追加。`DigestContext` を組み立てているテストは全て通るまで修正。

- [ ] **Step 3:**

```bash
uv run pytest -q
```

---

### Task 7: フロント — 概要パネルに vCenter 列

**Files:**
- 変更: [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts)
- 変更: [`frontend/src/panels/summary/SummaryPanel.tsx`](../../frontend/src/panels/summary/SummaryPanel.tsx)
- 変更: [`frontend/src/api/schemas.test.ts`](../../frontend/src/api/schemas.test.ts)（固定フィクスチャにキー追加）

- [ ] **Step 1: Zod**

`summaryHostMetricRowSchema` に `vcenter_label: z.string()` を追加する。

- [ ] **Step 2: UI**

`SummaryPanel.tsx` の高 CPU / 高メモリの表に、先頭列として `<th>vCenter</th>` と `<td>{h.vcenter_label}</td>` を追加する（既存の「ホスト」列はその右に残す）。

- [ ] **Step 3: フロントテスト**

```bash
cd /Users/moriyama/git/vcenter-event-assistant/frontend && npm test -- --run src/api/schemas.test.ts
```

必要なら `schemas.test.ts` のサマリモックに `vcenter_label: "x"` を足す。

---

### Task 8: 最終検証

```bash
cd /Users/moriyama/git/vcenter-event-assistant
uv run pytest -q
cd frontend && npm run build
```

---

## 自己レビュー（計画作成時）

| チェック | 結果 |
|----------|------|
| Spec（`name` のみ・`host` は列に使わない・空時 UUID 短縮・**`vcenter_label` を LLM 記号化必須**・ダッシュボード一致） | Task 2–5 でカバー |
| TBD / 空ステップ | なし |
| 型の一貫性 | バックエンドは `vcenter_label: str`、フロント Zod も `string` |

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-04-digest-vcenter-column-label.md`. Two execution options:**

1. **Subagent-Driven (recommended)** — タスクごとにサブエージェントを dispatch（superpowers:subagent-driven-development）。
2. **Inline Execution** — このセッションで executing-plans に沿い順に実装。

**Which approach?**
