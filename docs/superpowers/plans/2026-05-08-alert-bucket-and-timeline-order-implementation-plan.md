# Alert Bucket And Timeline Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** アラートをバケット単位（上位N種別+その他）で可視化し、タイムラインタブで時刻の昇順/降順を切り替えられるようにする。

**Architecture:** バックエンドの時系列バケット集計に alert 集計を同居させ、`chat_context_payloads` で `IncidentTimelineEntry(kind="alert")` を各バケットへ展開する。フロントは `TimelinePanel` に `alert_top_n` と並び順 UI を追加し、localStorage へ保存する。`IncidentTimelinePanel` は並び順 props で列順を切り替える。

**Tech Stack:** Python (FastAPI, SQLAlchemy, Pydantic), TypeScript (React, Zod, Vitest)

---

## File Structure / Responsibility

- Modify: `src/vcenter_event_assistant/services/chat_event_time_buckets.py`
  - イベントバケットに alert 上位N集計を追加
- Modify: `src/vcenter_event_assistant/services/chat_context_payloads.py`
  - バケット集計結果から alert timeline entries を生成
- Modify: `src/vcenter_event_assistant/api/schemas/chat.py`
  - `IncidentTimelineBuildRequest` に `alert_top_n` 追加
- Modify: `frontend/src/api/schemas.ts`
  - `incidentTimelineBuildRequestSchema` に `alert_top_n` 追加
- Modify: `frontend/src/api/buildIncidentTimelineBuildRequestPayload.ts`
  - `alert_top_n` を payload へ反映
- Modify: `frontend/src/panels/timeline/TimelinePanel.tsx`
  - `alert_top_n` 入力、時刻順トグル、localStorage 連携
- Modify: `frontend/src/panels/chat/IncidentTimelinePanel.tsx`
  - 並び順 props (`asc` / `desc`) 対応
- Modify: `frontend/src/panels/timeline/TimelinePanel.test.tsx`
  - `alert_top_n` 送信・永続化、並び順送信なし（表示のみ）確認
- Modify: `frontend/src/panels/chat/IncidentTimelinePanel.test.tsx`
  - 昇順/降順表示の検証
- Modify: `tests/test_chat_event_time_buckets.py`
  - alert 上位N+その他ロジックの単体テスト
- Modify: `tests/test_incident_timeline_api.py`
  - `alert_top_n` API契約、範囲外入力422

---

### Task 1: バックエンド Alert バケット集計（TDD）

**Files:**
- Modify: `tests/test_chat_event_time_buckets.py`
- Modify: `src/vcenter_event_assistant/services/chat_event_time_buckets.py`

- [ ] **Step 1: 失敗テストを追加（上位N+その他）**

```python
def test_build_chat_event_time_buckets_includes_alert_top_n_and_other() -> None:
    # Arrange: 同一バケットに複数 event_type と notable_score を持つイベント
    # Assert: max_notable_score 優先で top_n が選ばれ、残りが other へ入る
    ...
```

- [ ] **Step 2: RED確認**

Run: `uv run pytest tests/test_chat_event_time_buckets.py -q`  
Expected: FAIL（`alert_top_types` / `alert_other_count` が未実装）

- [ ] **Step 3: 最小実装**

```python
class AlertTypeBucketRow(BaseModel):
    event_type: str
    count: int = Field(ge=0)
    max_notable_score: int = Field(ge=0)

class EventTimeBucketRow(BaseModel):
    bucket_start_utc: datetime
    total: int = Field(ge=0)
    by_type: dict[str, int] = Field(default_factory=dict)
    alert_top_types: list[AlertTypeBucketRow] = Field(default_factory=list)
    alert_other_count: int = Field(default=0, ge=0)
```

```python
# 集計キー: (-max_notable_score, -count, event_type)
top = sorted(alert_stats.items(), key=... )[:alert_top_n]
rest = sorted(...)[alert_top_n:]
```

- [ ] **Step 4: GREEN確認**

Run: `uv run pytest tests/test_chat_event_time_buckets.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_chat_event_time_buckets.py src/vcenter_event_assistant/services/chat_event_time_buckets.py
git commit -m "feat: add alert top-n aggregation to event time buckets"
```

---

### Task 2: `/api/incident-timeline` 入力へ `alert_top_n` を追加（TDD）

**Files:**
- Modify: `tests/test_incident_timeline_api.py`
- Modify: `src/vcenter_event_assistant/api/schemas/chat.py`
- Modify: `src/vcenter_event_assistant/services/chat_context_payloads.py`

- [ ] **Step 1: 失敗テスト追加（受理・拒否）**

```python
async def test_post_incident_timeline_accepts_alert_top_n(client: AsyncClient) -> None:
    r = await client.post("/api/incident-timeline", json={..., "alert_top_n": 5})
    assert r.status_code == 200

async def test_post_incident_timeline_rejects_alert_top_n_out_of_range(client: AsyncClient) -> None:
    r = await client.post("/api/incident-timeline", json={..., "alert_top_n": 0})
    assert r.status_code == 422
```

- [ ] **Step 2: RED確認**

Run: `uv run pytest tests/test_incident_timeline_api.py -q`  
Expected: FAIL（`alert_top_n` 未定義）

- [ ] **Step 3: 最小実装**

```python
class IncidentTimelineBuildRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    from_time: datetime = Field(alias="from")
    to_time: datetime = Field(alias="to")
    ...
    alert_top_n: int = Field(default=3, ge=1, le=20)
```

```python
timeline_event_time_buckets = await build_chat_event_time_buckets(
    ...,
    bucket_sec=bucket_sec,
    alert_top_n=body.alert_top_n,
)
```

- [ ] **Step 4: GREEN確認**

Run: `uv run pytest tests/test_incident_timeline_api.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_incident_timeline_api.py src/vcenter_event_assistant/api/schemas/chat.py src/vcenter_event_assistant/services/chat_context_payloads.py
git commit -m "feat: support configurable alert top-n in incident timeline request"
```

---

### Task 3: タイムラインへ alert エントリをバケット単位で展開（TDD）

**Files:**
- Modify: `tests/test_incident_timeline_api.py`
- Modify: `src/vcenter_event_assistant/services/chat_context_payloads.py`

- [ ] **Step 1: 失敗テスト追加（最新時刻1点ではなくバケットごと）**

```python
async def test_post_incident_timeline_emits_alert_entries_per_bucket(client: AsyncClient) -> None:
    r = await client.post("/api/incident-timeline", json={..., "alert_top_n": 3, "include_period_metrics_cpu": True})
    assert r.status_code == 200
    # 複数バケットに alert kind が配置されることを検証
    ...
```

- [ ] **Step 2: RED確認**

Run: `uv run pytest tests/test_incident_timeline_api.py -q -k per_bucket`  
Expected: FAIL

- [ ] **Step 3: 最小実装**

```python
for row in timeline_event_time_buckets.buckets:
    for alert in row.alert_top_types:
        timeline_entries.append(
            IncidentTimelineEntry(
                timestamp_utc=row.bucket_start_utc,
                kind="alert",
                title=f"{alert.event_type} ({alert.count}件, max score={alert.max_notable_score})",
            )
        )
    if row.alert_other_count > 0:
        timeline_entries.append(
            IncidentTimelineEntry(
                timestamp_utc=row.bucket_start_utc,
                kind="alert",
                title=f"その他アラート ({row.alert_other_count}件)",
            )
        )
```

- [ ] **Step 4: GREEN確認**

Run: `uv run pytest tests/test_incident_timeline_api.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_incident_timeline_api.py src/vcenter_event_assistant/services/chat_context_payloads.py
git commit -m "feat: emit alert timeline entries per bucket"
```

---

### Task 4: フロント request schema / payload ビルダー拡張（TDD）

**Files:**
- Modify: `frontend/src/api/schemas.test.ts`
- Modify: `frontend/src/api/schemas.ts`
- Modify: `frontend/src/api/buildIncidentTimelineBuildRequestPayload.test.ts`
- Modify: `frontend/src/api/buildIncidentTimelineBuildRequestPayload.ts`

- [ ] **Step 1: 失敗テスト追加**

```ts
it('incidentTimelineBuildRequestSchema accepts alert_top_n', () => {
  const out = incidentTimelineBuildRequestSchema.parse({ ..., alert_top_n: 5 })
  expect(out.alert_top_n).toBe(5)
})

it('buildIncidentTimelineBuildRequestPayload includes alert_top_n', () => {
  const out = buildIncidentTimelineBuildRequestPayload({ ..., options: { ..., alertTopN: 7 } })
  expect(out.alert_top_n).toBe(7)
})
```

- [ ] **Step 2: RED確認**

Run: `npm run --prefix frontend test -- src/api/schemas.test.ts src/api/buildIncidentTimelineBuildRequestPayload.test.ts --maxWorkers=1`  
Expected: FAIL（`alert_top_n` 未対応）

- [ ] **Step 3: 最小実装**

```ts
export const incidentTimelineBuildRequestSchema = z.object({
  ...
  alert_top_n: z.number().int().min(1).max(20).optional(),
}).strict()
```

```ts
if (typeof options.alertTopN === 'number') {
  payload.alert_top_n = options.alertTopN
}
```

- [ ] **Step 4: GREEN確認**

Run: `npm run --prefix frontend test -- src/api/schemas.test.ts src/api/buildIncidentTimelineBuildRequestPayload.test.ts --maxWorkers=1`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/schemas.ts frontend/src/api/schemas.test.ts frontend/src/api/buildIncidentTimelineBuildRequestPayload.ts frontend/src/api/buildIncidentTimelineBuildRequestPayload.test.ts
git commit -m "feat: support alert top-n in timeline request payload"
```

---

### Task 5: TimelinePanel に `alert_top_n` と並び順トグル + localStorage（TDD）

**Files:**
- Modify: `frontend/src/panels/timeline/TimelinePanel.test.tsx`
- Modify: `frontend/src/panels/timeline/TimelinePanel.tsx`

- [ ] **Step 1: 失敗テスト追加**

```ts
it('alert_top_n を送信本文へ含める', async () => {
  // N入力 -> 生成 -> POST body.alert_top_n を検証
})

it('並び順設定を localStorage に保存・復元する', async () => {
  // desc -> asc 変更、再マウントで復元されること
})
```

- [ ] **Step 2: RED確認**

Run: `npm run --prefix frontend test -- src/panels/timeline/TimelinePanel.test.tsx --maxWorkers=1`  
Expected: FAIL

- [ ] **Step 3: 最小実装**

```ts
const TIMELINE_ALERT_TOP_N_STORAGE_KEY = 'timelineAlertTopN'
const TIMELINE_SORT_ORDER_STORAGE_KEY = 'timelineSortOrder'
type TimelineSortOrder = 'desc' | 'asc'
```

```ts
const [alertTopN, setAlertTopN] = useState<number>(...)
const [sortOrder, setSortOrder] = useState<TimelineSortOrder>(...)
```

```ts
const body = buildIncidentTimelineBuildRequestPayload({
  resolvedRange: ...,
  options: { ..., alertTopN },
})
```

- [ ] **Step 4: GREEN確認**

Run: `npm run --prefix frontend test -- src/panels/timeline/TimelinePanel.test.tsx --maxWorkers=1`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/timeline/TimelinePanel.tsx frontend/src/panels/timeline/TimelinePanel.test.tsx
git commit -m "feat: add alert top-n and sort order controls with local storage"
```

---

### Task 6: IncidentTimelinePanel の昇順/降順切替対応（TDD）

**Files:**
- Modify: `frontend/src/panels/chat/IncidentTimelinePanel.test.tsx`
- Modify: `frontend/src/panels/chat/IncidentTimelinePanel.tsx`
- Modify: `frontend/src/panels/timeline/TimelinePanel.tsx`

- [ ] **Step 1: 失敗テスト追加**

```ts
it('sortOrder=asc で古い列が左、新しい列が右になる', () => {
  render(<IncidentTimelinePanel timeline={timeline} sortOrder="asc" />)
  ...
})
```

- [ ] **Step 2: RED確認**

Run: `npm run --prefix frontend test -- src/panels/chat/IncidentTimelinePanel.test.tsx --maxWorkers=1`  
Expected: FAIL

- [ ] **Step 3: 最小実装**

```ts
export function IncidentTimelinePanel({
  timeline,
  sortOrder = 'desc',
}: {
  timeline: IncidentTimeline
  sortOrder?: 'asc' | 'desc'
}) {
  const orderedColumns = useMemo(() => [...timeline.columns].sort((a, b) => {
    if (sortOrder === 'asc') return a.timestamp_utc < b.timestamp_utc ? -1 : a.timestamp_utc > b.timestamp_utc ? 1 : 0
    return a.timestamp_utc < b.timestamp_utc ? 1 : a.timestamp_utc > b.timestamp_utc ? -1 : 0
  }), [timeline.columns, sortOrder])
}
```

- [ ] **Step 4: GREEN確認**

Run: `npm run --prefix frontend test -- src/panels/chat/IncidentTimelinePanel.test.tsx src/panels/timeline/TimelinePanel.test.tsx --maxWorkers=1`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/panels/chat/IncidentTimelinePanel.tsx frontend/src/panels/chat/IncidentTimelinePanel.test.tsx frontend/src/panels/timeline/TimelinePanel.tsx
git commit -m "feat: support timeline sort order toggle in timeline tab"
```

---

### Task 7: 総合検証と仕上げ

**Files:**
- Modify: （必要なら）`docs/superpowers/specs/2026-05-08-alert-bucket-and-timeline-order-design.md`

- [ ] **Step 1: バックエンド全体検証**

Run: `uv run pytest -q --maxfail=1`  
Expected: PASS

- [ ] **Step 2: フロント全体検証**

Run: `npm run --prefix frontend test -- --maxWorkers=1`  
Expected: PASS

- [ ] **Step 3: フロントビルド**

Run: `npm --prefix frontend run build`  
Expected: PASS

- [ ] **Step 4: 変更差分確認**

Run: `git status --short`  
Expected: この機能に関係するファイルのみ変更

- [ ] **Step 5: Commit（最終）**

```bash
git add src/vcenter_event_assistant/services/chat_event_time_buckets.py \
        src/vcenter_event_assistant/services/chat_context_payloads.py \
        src/vcenter_event_assistant/api/schemas/chat.py \
        frontend/src/api/schemas.ts frontend/src/api/buildIncidentTimelineBuildRequestPayload.ts \
        frontend/src/panels/timeline/TimelinePanel.tsx frontend/src/panels/chat/IncidentTimelinePanel.tsx \
        tests/test_chat_event_time_buckets.py tests/test_incident_timeline_api.py \
        frontend/src/api/schemas.test.ts frontend/src/api/buildIncidentTimelineBuildRequestPayload.test.ts \
        frontend/src/panels/timeline/TimelinePanel.test.tsx frontend/src/panels/chat/IncidentTimelinePanel.test.tsx

git commit -m "feat: bucketize alert timeline and add sort toggle in timeline tab"
```

---

## Self-Review

- Spec coverage: alert バケット化 / score優先 top-N / localStorage 保存 / 並び順トグル（タイムラインタブ限定）をすべてタスク化済み。
- Placeholder scan: TBD/TODO/曖昧語なし。
- Type consistency: `alert_top_n`（BE/FE）と `sortOrder`（FE）で命名統一済み。
