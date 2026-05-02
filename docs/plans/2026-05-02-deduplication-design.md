# コード重複の解消 — 設計ドキュメント

**日付:** 2026-05-02
**目的:** バックエンドの複数箇所に散在する同一ロジックを共通化し、保守性と可読性を向上させる。

## 背景

機能追加が続く中で、以下のパターンが複数ファイルにコピーされている:

1. `settings.py` — 「空文字 → None」正規化バリデータ × 5箇所
2. `schemas.py` — datetime → UTC 正規化バリデータ × 6箇所
3. `dashboard.py` / `digest_context.py` — CPU/メモリ ランキングクエリ（row_number OVER）
4. `dashboard.py` / `digest_context.py` — イベント種別 Top N + max_notable_score 算出
5. `chat_llm.py` — `run_period_chat` と `build_chat_preview` のペイロード構築
6. `chat_llm.py` / `digest_llm.py` — LLM 失敗ログ関数

## 設計方針

- **ロジックの移動のみ**: 外部から見える API（HTTP レスポンス、DB スキーマ）は一切変更しない
- **既存テストで回帰検知**: 新規テスト追加は最小限。既存の50本のテストスイートが回帰を検出する
- **段階的な統合**: 各重複を独立したタスクとし、1タスクずつ commit して安全に進める

## 各重複の解消方法

### 1. settings.py — 空文字正規化の共通化

`_normalize_empty_to_none(v)` をモジュールレベルに定義し、5つの `field_validator` から呼び出す。

### 2. schemas.py — UTC 正規化の共通化

`_normalize_to_utc(v)` を定義。ISO 文字列対応（DigestRead 用）も含めた単一関数とし、6つのバリデータから呼び出す。`HighCpuHostRow` と `HighMemHostRow` の `sampled_at_to_utc` は完全に同一なので統合可能。

### 3. CPU/メモリ ランキングクエリの共通化

新関数 `query_top_metric_hosts()` を `services/metric_ranking.py` に配置:

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

`dashboard.py`（`day_ago` ～ `now`）と `digest_context.py`（`from_utc` ～ `to_utc`）の両方がこれを呼ぶ。
`MetricSample` → `HighCpuHostRow`/`HighMemHostRow` への変換も共通関数にする。

### 4. イベント種別 Top N 集計の共通化

新関数 `query_top_event_type_buckets()` を `services/metric_ranking.py` に追加:

```python
async def query_top_event_type_buckets(
    session: AsyncSession,
    event_clauses: list,
    *,
    limit: int = 10,
) -> list[EventTypeBucket]:
```

`EventTypeBucket` は `digest_context.py` の `DigestEventTypeBucket` と `schemas.py` の `EventTypeCountRow` の両方の元データとなる。

### 5. chat ペイロード構築の共通化

`chat_llm.py` 内に `_prepare_chat_payload()` を定義:

```python
def _prepare_chat_payload(
    settings: Settings,
    context: DigestContext,
    messages: list[ChatMessage],
    period_metrics: PeriodMetricsPayload | None,
    event_time_buckets: EventTimeBucketsPayload | None,
    extra_vcenter_strings: Sequence[str] | None,
) -> tuple[dict, list[ChatMessage], dict[str, str]]:
```

`run_period_chat` と `build_chat_preview` の両方がこれを呼ぶ。

### 6. LLM 失敗ログの共通化

新関数を `services/llm_logging.py`（または既存の `llm_invoke.py`）に配置:

```python
def log_llm_failure(settings: Settings, purpose: str, exc: BaseException) -> None:
```

`chat_llm.py` と `digest_llm.py` の両方がこれを呼ぶ。
