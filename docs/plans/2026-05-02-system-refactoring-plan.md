# System Refactoring Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** システム全体の保守性・可読性を向上させるため、肥大化したスキーマの分割、ルーターからのDBクエリ分離、およびフロントエンドフックの分割を行う。

**Architecture:** 
1. バックエンド: 巨大な `schemas.py` をドメイン別に `schemas/` ディレクトリへ分割し、`__init__.py` で集約エクスポートする。
2. バックエンド: `events.py` ルーター内のSQLAlchemyクエリを `services/event_repository.py` へ抽出し、データアクセス層を分離する。
3. フロントエンド: `useMetricsPanelController.ts` からメトリクス取得ロジックを抽出する。

**Tech Stack:** Python, FastAPI, SQLAlchemy, Pydantic, React, TypeScript

---

### Task 1: `schemas.py` のドメイン別ディレクトリへの分割

**Files:**
- Create: `src/vcenter_event_assistant/api/schemas/__init__.py`
- Create: `src/vcenter_event_assistant/api/schemas/base.py`
- Modify: `src/vcenter_event_assistant/api/schemas.py` -> `src/vcenter_event_assistant/api/schemas/legacy.py` 等へ順次移動

**Step 1: スキーマ分割のためのディレクトリ作成とベースモデルの移動**

※ テスト駆動ではありませんが、既存の全テストが通過するかで構造の妥当性を検証します。

```bash
mkdir -p src/vcenter_event_assistant/api/schemas
touch src/vcenter_event_assistant/api/schemas/__init__.py
```

`src/vcenter_event_assistant/api/schemas/base.py` を作成し、Pydantic の共通設定（`BaseModel` のエイリアスジェネレータなど）を移動します。

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
```

**Step 2: 既存のテストを実行してエラーになることを確認**

```bash
mv src/vcenter_event_assistant/api/schemas.py src/vcenter_event_assistant/api/schemas/legacy.py
uv run pytest tests/
```
Expected: FAIL (ModuleNotFoundError)

**Step 3: `__init__.py` での再エクスポート実装**

`src/vcenter_event_assistant/api/schemas/__init__.py` を作成し、全てのエクスポートを維持します。これにより呼び出し元のインポート文を変更せずに済みます。

```python
from .legacy import *
```

**Step 4: テストのパス確認**

Run: `uv run pytest tests/`
Expected: PASS

**Step 5: コミット**

```bash
git add src/vcenter_event_assistant/api/schemas/
git rm src/vcenter_event_assistant/api/schemas.py
git commit -m "refactor: introduce schemas directory and base model"
```

---

### Task 2: イベントルーターからのデータアクセス分離 (`EventRepository` の作成)

**Files:**
- Create: `src/vcenter_event_assistant/services/event_repository.py`
- Create: `tests/test_event_repository.py`
- Modify: `src/vcenter_event_assistant/api/routes/events.py`

**Step 1: `EventRepository` の失敗するテストを作成**

`tests/test_event_repository.py` を作成します。

```python
import pytest
from datetime import datetime, timezone
from vcenter_event_assistant.services.event_repository import get_event_rate_series

@pytest.mark.asyncio
async def test_get_event_rate_series_empty(db_session):
    from_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    to_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    
    buckets = await get_event_rate_series(
        session=db_session,
        event_type="VmPoweredOnEvent",
        from_time=from_time,
        to_time=to_time,
        bucket_seconds=3600
    )
    assert len(buckets) == 24
    assert buckets[0]["count"] == 0
```

**Step 2: テストの失敗を確認**

Run: `uv run pytest tests/test_event_repository.py -v`
Expected: FAIL

**Step 3: `EventRepository` の実装**

`src/vcenter_event_assistant/services/event_repository.py` を作成します。

```python
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, cast, Integer, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from vcenter_event_assistant.db.models import EventRecord

def _epoch_seconds_expr(dialect_name: str):
    if dialect_name == "postgresql":
        return cast(func.floor(func.extract("epoch", EventRecord.occurred_at)), Integer)
    return cast(func.strftime("%s", EventRecord.occurred_at), Integer)

async def get_event_rate_series(
    session: AsyncSession,
    event_type: str,
    from_time: datetime,
    to_time: datetime,
    bucket_seconds: int,
    vcenter_id: uuid.UUID | None = None,
) -> list[dict[str, any]]:
    conditions: list[ColumnElement[bool]] = [
        EventRecord.event_type == event_type.strip(),
        EventRecord.occurred_at >= from_time,
        EventRecord.occurred_at <= to_time,
    ]
    if vcenter_id is not None:
        conditions.append(EventRecord.vcenter_id == vcenter_id)

    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else "sqlite"
    epoch_sec = _epoch_seconds_expr(dialect_name)
    bucket_epoch = epoch_sec - func.mod(epoch_sec, literal(bucket_seconds))

    q = select(bucket_epoch.label("bucket_epoch"), func.count().label("cnt")).where(*conditions).group_by(bucket_epoch)
    res = await session.execute(q)
    
    count_by_epoch = {int(row.bucket_epoch): int(row.cnt) for row in res.all()}
    
    from_ts = int(from_time.timestamp())
    to_ts = int(to_time.timestamp())
    first = (from_ts // bucket_seconds) * bucket_seconds
    last = (to_ts // bucket_seconds) * bucket_seconds
    
    buckets = []
    for s in range(first, last + bucket_seconds, bucket_seconds):
        dt = datetime.fromtimestamp(s, tz=timezone.utc)
        buckets.append({"bucket_start": dt, "count": count_by_epoch.get(s, 0)})
        
    return buckets
```

**Step 4: テストの成功を確認**

Run: `uv run pytest tests/test_event_repository.py -v`
Expected: PASS

**Step 5: コミット**

```bash
git add tests/test_event_repository.py src/vcenter_event_assistant/services/event_repository.py
git commit -m "feat: add event repository for rate series query"
```

---

### Task 3: `events.py` ルーターのリファクタリング

**Files:**
- Modify: `src/vcenter_event_assistant/api/routes/events.py`

**Step 1: ルーターのロジック置き換え**

`events.py` の `event_rate_series` を先ほど作成した関数を呼び出すように修正します（詳細は実装時に対応）。

**Step 2: 既存の統合テストのパス確認**

Run: `uv run pytest tests/ -k event`
Expected: PASS

**Step 3: コミット**

```bash
git add src/vcenter_event_assistant/api/routes/events.py
git commit -m "refactor: extract db query logic from event rate series router"
```

---

### Task 4: フロントエンドフックの分割 (`useMetricDataFetch` の作成)

**Files:**
- Create: `frontend/src/hooks/useMetricDataFetch.ts`
- Create: `frontend/src/hooks/useMetricDataFetch.test.ts`
- Modify: `frontend/src/hooks/useMetricsPanelController.ts`

**Step 1: 失敗するテストの作成**

`frontend/src/hooks/useMetricDataFetch.test.ts` を作成します。

```typescript
import { renderHook } from '@testing-library/react'
import { useMetricDataFetch } from './useMetricDataFetch'

describe('useMetricDataFetch', () => {
  it('should initialize with empty data', () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useMetricDataFetch(onError))
    expect(result.current.points).toEqual([])
    expect(result.current.loading).toBe(false)
  })
})
```

**Step 2: テストの失敗確認**

Run: `npm run test -- frontend/src/hooks/useMetricDataFetch.test.ts`
Expected: FAIL

**Step 3: 最小限の実装**

`frontend/src/hooks/useMetricDataFetch.ts` を作成します。

```typescript
import { useState } from 'react'
import { MetricPoint } from '../metrics/normalizeMetricSeriesResponse'

export function useMetricDataFetch(onError: (e: string | null) => void) {
  const [points, setPoints] = useState<MetricPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [metricTotal, setMetricTotal] = useState<number | null>(null)

  return { points, setPoints, loading, setLoading, metricTotal, setMetricTotal }
}
```

**Step 4: テストの成功確認**

Run: `npm run test -- frontend/src/hooks/useMetricDataFetch.test.ts`
Expected: PASS

**Step 5: コミット**

```bash
git add frontend/src/hooks/useMetricDataFetch*
git commit -m "feat: extract useMetricDataFetch hook for metrics panel"
```
