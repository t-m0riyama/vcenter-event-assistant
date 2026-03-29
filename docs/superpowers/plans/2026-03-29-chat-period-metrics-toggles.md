# チャット期間メトリクス（4 トグル・バケット時系列）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: **`@superpowers:subagent-driven-development`**（推奨）または **`@superpowers:executing-plans`**。ステップはチェックボックス（`- [ ]`）で追跡する。
>
> **TDD:** **`@superpowers:test-driven-development`** を厳守する。各タスクで **失敗するテストを先に書く → `uv run pytest` で RED を確認（失敗理由が「未実装／期待どおりの不足」であること）→ 最小実装 → GREEN → リファクタ（緑のまま）**。**本番コードをテストより先に書かない**（試作スクリプトは捨てる）。

**Goal:** 期間コンテキスト付きチャットで、**CPU 使用率・メモリ使用率・ディスク IO・ネットワーク IO** を **個別トグル**で LLM 入力 JSON に含め、**高負荷判定は行わず**、指定期間のメトリクスを **時間バケット平均などで間引いた時系列**として送る。既存の **「CPU 高負荷とイベントの近接集約」**（`include_cpu_event_correlation` / `build_cpu_event_correlation`）は **廃止**し、関連コード・テスト・ドキュメントを削除する。

**Architecture:** `MetricSample` を期間・`vcenter_id`（任意）で絞り、カテゴリごとに `metric_key` 集合を定義（[`host_perf_counters.py`](../../src/vcenter_event_assistant/collectors/host_perf_counters.py) の `_TARGET_SPECS` と整合）。**バケット境界**は期間長に応じて動的（上限バケット数で幅を調整）。集計は **SQL `GROUP BY`（SQLite / PostgreSQL 両対応）**でバケット平均・件数を算出。結果は Pydantic モデル `PeriodMetricsPayload`（仮名）に載せ、[`run_period_chat`](../../src/vcenter_event_assistant/services/chat_llm.py) が `digest_context` とマージした JSON を既存のトークン予算ロジックに通す。**チャット用 `digest_context` からは `high_cpu_hosts` / `high_mem_hosts` を除外**し、メトリクスは `period_metrics` に一本化（ピーク上位との二重を避ける）。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.0 async、pytest、`uv run`；React、TypeScript、Zod、Vitest。

**関連 spec:** ブレインストーミング確定事項（間引き時系列・相関廃止）を本ファイルが単一参照とする。別途 `docs/superpowers/specs/` に分割 spec がある場合は整合させる。

---

## ファイル構成（作成・変更・削除）

| パス | 責務 |
| ---- | ---- |
| **Create** [`src/vcenter_event_assistant/services/chat_period_metrics.py`](../../src/vcenter_event_assistant/services/chat_period_metrics.py) | `metric_key` カテゴリ定数、バケット幅決定、`build_chat_period_metrics(...)`（`AsyncSession`, `from_utc`, `to_utc`, `vcenter_id`, トグル 4 つ、Settings または定数で上限）。戻り値は **すべてオフなら `None`**。 |
| **Create** [`tests/test_chat_period_metrics.py`](../../tests/test_chat_period_metrics.py) | SQLite メモリ DB に `MetricSample` を投入し、バケット平均・ホスト上限・トグル OFF でキーが出ないことを検証。 |
| **Modify** [`src/vcenter_event_assistant/settings.py`](../../src/vcenter_event_assistant/settings.py) | 任意: `CHAT_METRICS_MAX_BUCKETS`, `CHAT_METRICS_MAX_HOSTS_PER_CATEGORY`, `CHAT_METRICS_BUCKET_*` 等（YAGNI なら定数のみから開始し、後続コミットで追加可）。 |
| **Modify** [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py) | `ChatRequest` から `include_cpu_event_correlation` / `cpu_correlation_threshold_pct` / `cpu_correlation_window_minutes` を削除。`include_period_metrics_cpu` 等 **4 つの `bool = False`** を追加（またはネストモデル `PeriodMetricsInclusion`）。`PeriodMetricsPayload` 用モデル（レスポンスには含めず LLM 内部用でも可）。 |
| **Modify** [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py) | `build_cpu_event_correlation` 呼び出し削除。`build_digest_context` の後、トグルが 1 つでも真なら `build_chat_period_metrics` を await。`run_period_chat` に `period_metrics` と **チャット用 digest dict**（`high_cpu_hosts` / `high_mem_hosts` 除去済み）を渡す。 |
| **Modify** [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py) | `correlation: CpuEventCorrelationPayload \| None` を削除し、`period_metrics: dict \| None` または Pydantic を受け取る。`payload` マージから `cpu_event_correlation` を削除し、`period_metrics` キーを追加。`_CHAT_SYSTEM_PROMPT` と `_merged_context_user_block` から相関説明を削除し、`period_metrics`（バケット平均・間引き）の説明を追加。 |
| **Delete** [`src/vcenter_event_assistant/services/correlation_context.py`](../../src/vcenter_event_assistant/services/correlation_context.py) | 参照ゼロを grep で確認後に削除。 |
| **Delete** [`tests/test_correlation_context.py`](../../tests/test_correlation_context.py) | 同上。 |
| **Modify** [`tests/test_chat_api.py`](../../tests/test_chat_api.py) | 相関スパイを **期間メトリクスビルダ**のスパイに差し替え。新フラグが POST に載るケースを追加。 |
| **Modify** [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py) | `correlation` 引数を `period_metrics` に変更。ユーザーブロック文字列の期待から `cpu_event_correlation` を除去。 |
| **Modify** [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts) | チャットリクエスト Zod から相関フィールドを削除し、4 トグルを追加。 |
| **Modify** [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx) | `includeCpuEventCorrelation` を 4 つの `useState(false)` に置換。POST body に新キーを載せる。 |
| **Modify** [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx) | 相関チェックのテストを **いずれかのトグル ON** で新キーが送られるテストに変更。 |
| **Modify** [`docs/development.md`](../../docs/development.md) | `POST /api/chat` の説明を相関から **期間メトリクス 4 トグル + バケット時系列** に更新。 |
| **Modify** [`.env.example`](../../.env.example) | チャットメトリクス上限がある場合はコメント付きで追記。 |

**変更しないもの:** [`digest_context.py`](../../src/vcenter_event_assistant/services/digest_context.py) の **`build_digest_context` 本体**（ダイジェスト・他呼び出しの後方互換）。チャットだけ **シリアライズ後にキーを落とす**か、**薄いラッパ**で `DigestContext` をコピーして空リストにするかは実装時に選択（テストで「LLM に渡す dict に `high_cpu_hosts` が無い」ことを断言）。

---

## メトリクスキー（カテゴリ対応）

実装時は [`host_perf_counters.py`](../../src/vcenter_event_assistant/collectors/host_perf_counters.py) の `_TARGET_SPECS` と **同一文字列**を定数化する。

- **CPU:** `host.cpu.usage_pct`（[`digest_context.py`](../../src/vcenter_event_assistant/services/digest_context.py) と同じ）
- **Memory:** `host.mem.usage_pct`
- **Disk IO:** `host.disk.read_kbps`, `host.disk.write_kbps`, `host.disk.usage_pct`（必要に応じて `host.disk.*` の採用範囲をテストで固定）
- **Network IO:** `host.net.bytes_rx_kbps`, `host.net.bytes_tx_kbps`, `host.net.usage_kbps`（MVP はスループット系。errors/dropped はトークン圧力が高ければ Phase 2）

---

## バケット・上限（既定の提案値）

| パラメータ | 提案 | 説明 |
| ---------- | ---- | ---- |
| `max_buckets` | 48 | バケット数上限。期間が長いときは **バケット幅を伸ばして**件数を抑える。 |
| `max_hosts_per_category` | 15 | カテゴリ内で系列を出す **ホスト（entity）上位件数**。並べ替えキーは期間内 **max(value)** が高い順などテストで固定。 |
| バケット幅 | 動的 | 例: 期間 ≤ 6h → 15 分、≤ 48h → 1h、それ以上 → 6h を目安に、`max_buckets` を超えないよう切り上げ。 |

---

## ブランチ方針

- **ベース:** `main`（作業前に `git pull`）。
- **ブランチ名例:** `feat/chat-period-metrics-toggles`

---

### Task 1: `build_chat_period_metrics` のコア集計（TDD）

**Files:**

- Create: [`src/vcenter_event_assistant/services/chat_period_metrics.py`](../../src/vcenter_event_assistant/services/chat_period_metrics.py)
- Create: [`tests/test_chat_period_metrics.py`](../../tests/test_chat_period_metrics.py)

**契約:**

- 4 トグルすべて `False` → **`None`**（呼び出し側はキーを付与しない）。
- 少なくとも 1 つ `True` → `PeriodMetricsPayload` 相当の dict / モデル。各オンカテゴリのみキーが存在。
- SQLite（pytest 既定の in-memory）で **バケット平均**が期待どおり（手計算可能な 2〜3 サンプル）。
- `from_utc >= to_utc` は `ValueError`（既存パターンに合わせる）。

- [ ] **Step 1: 失敗するテストを書く**

  `test_chat_period_metrics.py` に、**未実装の** `build_chat_period_metrics` を import して `pytest.raises(ImportError)` または **空実装で AssertionError** になるテストを書く。具体例:

  - `MetricSample` 2 件同一ホスト・同一 `metric_key`・異なる `sampled_at` が同一バケット → `avg` が算術平均、`n` が 2。
  - トグル CPU のみ ON のとき、結果に `cpu` があり `memory` キーが無い。

- [ ] **Step 2: RED を確認**

  Run: `uv run pytest tests/test_chat_period_metrics.py -v --override-ini addopts=`

  Expected: **失敗**（ImportError または AssertionError）。

- [ ] **Step 3: 最小実装**

  SQLAlchemy でバケット式（SQLite: `(strftime('%s', sampled_at) / (bucket_seconds))` の整数化 等。PostgreSQL 分岐が必要なら `compile.dialect.name` で分岐するヘルパを同一ファイルに置く）。

- [ ] **Step 4: GREEN**

  Run: `uv run pytest tests/test_chat_period_metrics.py -v --override-ini addopts=`

- [ ] **Step 5: ruff**

  Run: `uv run ruff check src/vcenter_event_assistant/services/chat_period_metrics.py tests/test_chat_period_metrics.py`

- [ ] **Step 6: Commit**

  ```bash
  git add src/vcenter_event_assistant/services/chat_period_metrics.py tests/test_chat_period_metrics.py
  git commit -m "feat(chat): add bucketed period metrics builder for LLM context"
  ```

---

### Task 2: `ChatRequest` スキーマと相関フィールドの削除（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/api/schemas.py`](../../src/vcenter_event_assistant/api/schemas.py)
- Modify: [`tests/test_chat_api.py`](../../tests/test_chat_api.py)（既存 POST ボディの期待を更新）

- [ ] **Step 1: 失敗するテストを先に変更**

  `tests/test_chat_api.py` の `_chat_body()` および相関関連アサーションを、**新フィールド名**（例: `include_period_metrics_cpu: false`）を含む形に変更し、**まだ schemas を変えていない**ならバリデーションエラーで RED。

- [ ] **Step 2: RED 確認**

  Run: `uv run pytest tests/test_chat_api.py -v --override-ini addopts=`

- [ ] **Step 3: `ChatRequest` を実装**

  相関 3 フィールド削除、4 トグル追加。Field の `description` は日本語で簡潔に。

- [ ] **Step 4: GREEN**

  Run: `uv run pytest tests/test_chat_api.py -v --override-ini addopts=`

- [ ] **Step 5: Commit**

---

### Task 3: `chat` ルートと `run_period_chat` の配線（TDD）

**Files:**

- Modify: [`src/vcenter_event_assistant/api/routes/chat.py`](../../src/vcenter_event_assistant/api/routes/chat.py)
- Modify: [`src/vcenter_event_assistant/services/chat_llm.py`](../../src/vcenter_event_assistant/services/chat_llm.py)
- Modify: [`tests/test_chat_llm.py`](../../tests/test_chat_llm.py)

**契約:**

- `build_cpu_event_correlation` は **import されない**。
- `run_period_chat(..., period_metrics=...)` で、モック HTTP が受け取る user ブロックに **`period_metrics`** 文字列（またはキー）が含まれる。
- `digest_context` から `high_cpu_hosts` / `high_mem_hosts` が **除かれた** dict がマージに使われる（`test_chat_llm` で `model_dump` 後に `pop` した結果を検証するか、キャプチャ文字列で `"high_cpu_hosts": []` が無いことを確認）。

- [ ] **Step 1: テストを先に更新して RED**

  `test_chat_llm.py` の `test_run_period_chat_includes_correlation_in_user_block_when_set` を **`period_metrics` 付き**にリネーム・変更。`correlation=` を削除。

- [ ] **Step 2: 実装**

  `chat.py` で `period_metrics = await build_chat_period_metrics(...)`（全オフならスキップ）。`run_period_chat` シグネチャ更新。

- [ ] **Step 3: GREEN**

  Run: `uv run pytest tests/test_chat_llm.py tests/test_chat_api.py -v --override-ini addopts=`

- [ ] **Step 4: Commit**

---

### Task 4: 相関モジュールとテストの削除

**Files:**

- Delete: [`src/vcenter_event_assistant/services/correlation_context.py`](../../src/vcenter_event_assistant/services/correlation_context.py)
- Delete: [`tests/test_correlation_context.py`](../../tests/test_correlation_context.py)

- [ ] **Step 1: grep で参照確認**

  Run: `rg "correlation_context|build_cpu_event_correlation|CpuEventCorrelation" -S src tests frontend`

- [ ] **Step 2: 残参照をゼロにしてからファイル削除**

- [ ] **Step 3: 全テスト**

  Run: `uv run pytest -q --override-ini addopts=`

- [ ] **Step 4: Commit**

  ```bash
  git commit -m "refactor(chat): remove CPU-event proximity correlation"
  ```

---

### Task 5: フロントエンド（TDD）

**Files:**

- Modify: [`frontend/src/api/schemas.ts`](../../frontend/src/api/schemas.ts)
- Modify: [`frontend/src/panels/chat/ChatPanel.tsx`](../../frontend/src/panels/chat/ChatPanel.tsx)
- Modify: [`frontend/src/panels/chat/ChatPanel.test.tsx`](../../frontend/src/panels/chat/ChatPanel.test.tsx)

- [ ] **Step 1: テストを先に更新（RED）**

  `ChatPanel.test.tsx` で相関の期待を削除し、例: **`include_period_metrics_cpu: true`** のみ ON にしたとき POST body に含まれることを期待。

- [ ] **Step 2: Zod + UI 実装**

  4 チェックボックス（ラベルは日本語で短く）。

- [ ] **Step 3: GREEN**

  Run: `npm test -- --run src/panels/chat/ChatPanel.test.tsx`（プロジェクトの既定スクリプトに合わせる）

- [ ] **Step 4: Commit**

---

### Task 6: ドキュメントと `.env.example`

**Files:**

- Modify: [`docs/development.md`](../../docs/development.md)
- Modify: [`.env.example`](../../.env.example)（Settings を追加した場合のみ）

- [ ] **Step 1:** `POST /api/chat` の JSON フィールド説明を最新化。
- [ ] **Step 2:** Commit（`docs:` または `docs(chat):`）。

---

## 回帰確認（完了前必須）

```bash
uv run pytest -q --override-ini addopts=
uv run ruff check src tests
# フロントがある場合
npm run build
npm test -- --run
```

---

## Plan review loop（任意だが推奨）

1. 本ファイルと（存在すれば）`docs/superpowers/specs/` 内の spec を **`plan-document-reviewer` サブエージェント**に渡し、抜け・矛盾・過剰スコープをレビューさせる。
2. 指摘があれば本ファイルを修正し、最大 3 回まで再レビュー。
3. 人間レビュー OK 後に実装へ。

---

## Execution handoff

**Plan complete and saved to [`docs/superpowers/plans/2026-03-29-chat-period-metrics-toggles.md`](2026-03-29-chat-period-metrics-toggles.md).**

**実行オプション:**

1. **Subagent-Driven（推奨）** — タスクごとに新しいサブエージェントを起動し、タスク間でレビュー。**必須サブスキル:** `@superpowers:subagent-driven-development`
2. **Inline Execution** — 本セッションで `@superpowers:executing-plans` に従いチェックポイント付きで一括実行。

**どちらで進めますか？**（実装開始の明示指示が無い限り、エージェントは本ファイルの編集のみとし、コード変更は行わない。）
