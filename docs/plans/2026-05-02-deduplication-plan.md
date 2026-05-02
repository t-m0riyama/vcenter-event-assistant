# コード重複の解消 — 実装プラン

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** バックエンドの6箇所のコード重複を共通関数に統合し、保守性を向上させる。外部 API の振る舞いは変更しない。

**Architecture:** 共通ロジックをヘルパー関数として抽出し、既存の呼び出し元から委譲する。新ファイルは `services/metric_ranking.py` のみ。

**Tech Stack:** Python, FastAPI, SQLAlchemy, Pydantic

---

### Task 1: `settings.py` — 空文字正規化バリデータの共通化

**Files:**
- Modify: `src/vcenter_event_assistant/settings.py`

**Step 1: 共通ヘルパー `_normalize_empty_to_none` を定義**

`Settings` クラスの直前にモジュールレベル関数を追加する:

```python
def _normalize_empty_to_none(v: object) -> str | None:
    """空文字・空白のみは None に正規化する（複数の field_validator 共通）。"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v).strip() or None
```

**Step 2: 5つの既存バリデータのロジック本体を `_normalize_empty_to_none(v)` の呼び出しに置き換え**

対象（すべて `return _normalize_empty_to_none(v)` に簡素化）:
- `empty_log_path_to_none`（L94）
- `empty_vcenter_proxy_to_none`（L105）
- `empty_alert_settings_to_none`（L116）
- `empty_llm_optional_str_to_none`（L331）
- `empty_langsmith_str_to_none`（L351）
- `empty_copilot_cli_path_to_none`（L362）

**Step 3: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス

**Step 4: Commit**

```bash
git add src/vcenter_event_assistant/settings.py
git commit -m "refactor: extract _normalize_empty_to_none in settings.py"
```

---

### Task 2: `schemas.py` — datetime UTC 正規化バリデータの共通化

**Files:**
- Modify: `src/vcenter_event_assistant/api/schemas.py`

**Step 1: 共通関数 `_normalize_to_utc` をファイル上部に定義**

```python
def _normalize_to_utc(v: object) -> datetime:
    """datetime / ISO-8601 文字列を UTC に正規化する（複数の field_validator 共通）。"""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise TypeError("expected datetime or ISO-8601 string")
```

**Step 2: 6箇所のバリデータを `_normalize_to_utc(v)` 呼び出しに置き換え**

対象:
- `EventRead.occurred_at_to_utc`（L73）
- `MetricPoint.sampled_at_to_utc`（L113）
- `HighCpuHostRow.sampled_at_to_utc`（L150）
- `HighMemHostRow.sampled_at_to_utc`（L174）
- `DigestRead.digest_datetimes_to_utc`（L349）

各バリデータのチェック（`not isinstance(v, datetime)` → `TypeError`）は `_normalize_to_utc` が担う。
`EventRead` / `MetricPoint` / `HighCpuHostRow` / `HighMemHostRow` は datetime のみ受け取るが、共通関数は str も対応しているため互換。

**Step 3: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス

**Step 4: Commit**

```bash
git add src/vcenter_event_assistant/api/schemas.py
git commit -m "refactor: extract _normalize_to_utc in schemas.py"
```

---

### Task 3: CPU/メモリ ランキングクエリの共通化

**Files:**
- Create: `src/vcenter_event_assistant/services/metric_ranking.py`
- Modify: `src/vcenter_event_assistant/api/routes/dashboard.py`
- Modify: `src/vcenter_event_assistant/services/digest_context.py`

**Step 1: `services/metric_ranking.py` に共通クエリ関数を作成**

```python
async def query_top_metric_hosts(
    session: AsyncSession,
    metric_key: str,
    from_utc: datetime,
    to_utc: datetime,
    *,
    vcenter_id: uuid.UUID | None = None,
    limit: int = 10,
) -> list[MetricSample]:
```

`row_number() OVER(PARTITION BY vcenter_id, entity_moid ORDER BY value DESC, sampled_at DESC)` のランキングクエリを1箇所に集約する。

**Step 2: `MetricSample` → `HighCpuHostRow` / `HighMemHostRow` 変換ヘルパーを追加**

```python
def metric_samples_to_high_host_rows(
    rows: list[MetricSample],
    label_map: dict[uuid.UUID, str],
    *,
    row_class: type[HighCpuHostRow] | type[HighMemHostRow],
) -> list[HighCpuHostRow] | list[HighMemHostRow]:
```

**Step 3: `dashboard.py` を書き換え**

`dashboard.py` の CPU ランキング（L115-138）とメモリランキング（L140-163）を、`query_top_metric_hosts()` + `metric_samples_to_high_host_rows()` の呼び出しに置き換え。

**Step 4: `digest_context.py` を書き換え**

`digest_context.py` の CPU ランキング（L231-259）とメモリランキング（L261-289）を同様に置き換え。

**Step 5: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス（`test_dashboard_summary.py` が回帰を検出する）

**Step 6: Commit**

```bash
git add src/vcenter_event_assistant/services/metric_ranking.py \
        src/vcenter_event_assistant/api/routes/dashboard.py \
        src/vcenter_event_assistant/services/digest_context.py
git commit -m "refactor: extract metric ranking queries into metric_ranking.py"
```

---

### Task 4: イベント種別 Top N 集計の共通化

**Files:**
- Modify: `src/vcenter_event_assistant/services/metric_ranking.py`
- Modify: `src/vcenter_event_assistant/api/routes/dashboard.py`
- Modify: `src/vcenter_event_assistant/services/digest_context.py`

**Step 1: `metric_ranking.py` にイベント種別集計関数を追加**

```python
@dataclass
class EventTypeBucketResult:
    event_type: str
    event_count: int
    max_notable_score: int

async def query_top_event_type_buckets(
    session: AsyncSession,
    event_clauses: list,
    *,
    limit: int = 10,
) -> list[EventTypeBucketResult]:
```

この関数内に `delta_map` のロード → GROUP BY → 全行走査で max_notable_score 算出のロジックをまとめる。

**Step 2: `dashboard.py` を書き換え**

`dashboard.py` L73-113 を `query_top_event_type_buckets()` 呼び出しに置き換え、結果を `EventTypeCountRow` に変換。

**Step 3: `digest_context.py` を書き換え**

`digest_context.py` L190-229 を同様に置き換え、結果を `DigestEventTypeBucket` に変換。

**Step 4: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス

**Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/metric_ranking.py \
        src/vcenter_event_assistant/api/routes/dashboard.py \
        src/vcenter_event_assistant/services/digest_context.py
git commit -m "refactor: extract event type bucket aggregation into metric_ranking.py"
```

---

### Task 5: `chat_llm.py` — ペイロード構築の共通化

**Files:**
- Modify: `src/vcenter_event_assistant/services/chat_llm.py`

**Step 1: 共通関数 `_prepare_chat_payload` を定義**

```python
def _prepare_chat_payload(
    settings: Settings,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    extra_vcenter_strings: Sequence[str] | None,
) -> tuple[dict[str, Any], list[ChatMessage], dict[str, str]]:
    """
    digest_context から high_cpu/mem を除外 → payload 構築 → 匿名化。
    Returns: (payload, trimmed_messages, reverse_map)
    """
```

`build_chat_preview` と `run_period_chat` の共通部分（L238-257 と L300-320）を抽出。

**Step 2: `build_chat_preview` と `run_period_chat` を `_prepare_chat_payload` 呼び出しに置き換え**

`build_chat_preview` では `reverse_map` は不要（preview のためトークンのまま返す）なので `_` で無視。
`run_period_chat` では `reverse_map` を `deanonymize_text` に渡す。

**Step 3: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス（`test_chat_llm.py`, `test_chat_preview_api.py` が回帰を検出する）

**Step 4: Commit**

```bash
git add src/vcenter_event_assistant/services/chat_llm.py
git commit -m "refactor: extract _prepare_chat_payload in chat_llm.py"
```

---

### Task 6: LLM 失敗ログの共通化

**Files:**
- Modify: `src/vcenter_event_assistant/services/llm_invoke.py`
- Modify: `src/vcenter_event_assistant/services/chat_llm.py`
- Modify: `src/vcenter_event_assistant/services/digest_llm.py`

**Step 1: `llm_invoke.py` に共通ログ関数を追加**

```python
def log_llm_failure(
    settings: Settings,
    purpose: str,
    exc: BaseException,
) -> None:
    """LLM 呼び出し失敗の運用ログ（API キーは出力しない）。"""
    prof = resolve_llm_profile(settings, purpose=purpose)
    if prof.provider == "openai_compatible":
        base = (prof.base_url or "").rstrip("/")
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=openai_compatible base_url=%s model=%s exc=%r",
            purpose, base, prof.model, exc, exc_info=True,
        )
    elif prof.provider == "copilot_cli":
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=copilot_cli model=%s exc=%r",
            purpose, prof.model, exc, exc_info=True,
        )
    else:
        _logger.warning(
            "%s LLM 呼び出しに失敗 provider=gemini model=%s exc=%r",
            purpose, prof.model, exc, exc_info=True,
        )
```

**Step 2: `chat_llm.py` から `_log_chat_llm_failure` を削除し、`log_llm_failure(settings, "chat", e)` に置き換え**

**Step 3: `digest_llm.py` から `_log_digest_llm_failure` を削除し、`log_llm_failure(settings, "digest", e)` に置き換え**

**Step 4: テスト実行**

Run: `uv run pytest tests/ -x -q`
Expected: 全テストパス

**Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/llm_invoke.py \
        src/vcenter_event_assistant/services/chat_llm.py \
        src/vcenter_event_assistant/services/digest_llm.py
git commit -m "refactor: unify LLM failure logging into llm_invoke.py"
```

---

## 完了の検証

1. `uv run pytest tests/ -x -q` が全テストパス
2. 重複していたコードが各共通関数に集約されていることの確認
3. 外部 API（HTTP レスポンス）に変更がないことの確認（既存テストによる保証）
