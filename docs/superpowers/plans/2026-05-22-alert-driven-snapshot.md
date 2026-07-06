# アラート連動スナップショット Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** タイムライン生成（`POST /api/incident-timeline`）時の暗黙的な auto スナップショット保存を廃止し、スケジューラの `AlertRule` が **新規 firing** したときだけ `IncidentTimelineManualSnapshot`（`snapshot_kind=auto`）を保存する。明示的な `POST /snapshots/manual` は変更しない。

**Architecture:** 永続化ロジックを [`incident_timeline_snapshot.py`](src/vcenter_event_assistant/services/incident_timeline_snapshot.py) に集約する。タイムライン API からは呼び出しを削除する。`AlertEvaluator._notify` は `state.state == "firing"` のときだけスナップショットサービスを呼び、メール送信・`AlertHistory` は既存どおり。期間は `fired_at - alert_snapshot_lookback_hours` 〜 `now(UTC)` で `build_request_payload` を組み立てる。

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 async, pytest + httpx, Pydantic v2, Alembic 不要（既存 JSON カラムのみ使用）

---

## Git / ブランチ方針

- **`main` 上での直接実装・直接コミットは行わない**（ユーザーが **`main` でよい**と明示した場合のみ例外）。
- 作業は **feature ブランチ**、または **`git worktree` による隔離ワークツリー**上で行う。
- **コード変更・コミットに入る前**に、読み取り専用のシェルで少なくとも次を実行し、作業報告の冒頭で短文共有する。
  - `git branch --show-current`（空なら detached の可能性）
  - `git rev-parse --show-toplevel`
  - 可能なら `pwd`（`.worktrees/...` かリポジトリ直下かの目安）
- **実装開始（プラン Task 1 のコード編集前）**は Superpowers の **`using-git-worktrees`** に従い隔離ワークツリーを用意する。
  - 本リポジトリではプロジェクト直下の **`.worktrees/`** を優先する（なければ `worktrees/`）。プロジェクトローカル配置の場合は、作成前に **`git check-ignore`** で誤追跡を防ぐ。
  - 推奨: ブランチ `feature/alert-driven-snapshot`、ワークツリー `.worktrees/feature-alert-driven-snapshot/`
- **`main` へのマージ・`git push origin main`** はユーザーの明示がない限りエージェントから実行しない。

詳細: [docs/snippets/git-branch-policy-for-plans.md](../snippets/git-branch-policy-for-plans.md)

---

## ファイル構成（変更マップ）

| ファイル | 責務 |
|----------|------|
| **Create** [`src/vcenter_event_assistant/services/incident_timeline_snapshot.py`](src/vcenter_event_assistant/services/incident_timeline_snapshot.py) | `build_alert_rule_snapshot_*`、DB 永続化、重複防止 |
| **Modify** [`src/vcenter_event_assistant/api/routes/incident_timeline.py`](src/vcenter_event_assistant/api/routes/incident_timeline.py) | `_persist_auto_trigger_snapshots` 削除、`post_incident_timeline` から呼び出し削除 |
| **Modify** [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py) | firing 通知時にスナップショット保存 |
| **Modify** [`src/vcenter_event_assistant/settings.py`](src/vcenter_event_assistant/settings.py) | `alert_snapshot_lookback_hours` 追加 |
| **Create** [`tests/test_incident_timeline_snapshot.py`](tests/test_incident_timeline_snapshot.py) | サービス単体・Alert 連携 |
| **Modify** [`tests/test_incident_timeline_api.py`](tests/test_incident_timeline_api.py) | POST 後に auto が増えないテストへ置換 |
| **Modify** [`tests/test_alert_settings.py`](tests/test_alert_settings.py) | 新設定の既定値 |
| **Create** [`docs/superpowers/specs/2026-05-22-alert-driven-snapshot-design.md`](docs/superpowers/specs/2026-05-22-alert-driven-snapshot-design.md) | 要件・非目標の正本 |

**非目標:** タイムライン JSON 上の自動トリガー行（`critical_burst` 等）の削除、既存 DB 内の過去 auto 行の削除、`graph_context` の自動付与。

---

## 契約（実装で固定する値）

- **`trigger_id`:** `alert_rule_{rule_id}_{context_slug}` — `context_slug` は `re.sub(r"[^a-z0-9]+", "_", context_key.lower()).strip("_")`（既存テストの snake_case 制約 `[a-z]+(?:_[a-z]+)*` に合わせる）
- **`trigger_evidence`:** `{"trigger_type": "alert_rule", "rule_id": int, "rule_name": str, "context_key": str, "state": "firing", "fired_at_utc": "...", "details": str}`
- **重複防止:** `(snapshot_kind="auto", trigger_id, from_time, to_time, timestamp_utc)` が既存なら INSERT スキップ
- **resolved 時:** スナップショット保存しない

---

### Task 0: ワークツリー準備（コード編集前）

- [ ] **Step 1:** 読み取り専用でブランチ確認

```bash
git branch --show-current
git rev-parse --show-toplevel
pwd
```

- [ ] **Step 2:** Superpowers `using-git-worktrees` に従い `.worktrees/feature-alert-driven-snapshot/` とブランチ `feature/alert-driven-snapshot` を作成し、そのディレクトリで以降の作業を行う

---

### Task 1: 設定 `alert_snapshot_lookback_hours`

**Files:**
- Modify: [`src/vcenter_event_assistant/settings.py`](src/vcenter_event_assistant/settings.py) — `AlertSettingsMixin` 内
- Test: [`tests/test_alert_settings.py`](tests/test_alert_settings.py)

- [ ] **Step 1: Write the failing test**

`tests/test_alert_settings.py` に追加:

```python
def test_alert_snapshot_lookback_hours_default():
    settings = Settings()
    assert settings.alert_snapshot_lookback_hours == 2


def test_alert_snapshot_lookback_hours_env_override(monkeypatch):
    monkeypatch.setenv("ALERT_SNAPSHOT_LOOKBACK_HOURS", "4")
    settings = Settings()
    assert settings.alert_snapshot_lookback_hours == 4
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_alert_settings.py::test_alert_snapshot_lookback_hours_default -v
```

Expected: FAIL — `Settings` has no attribute `alert_snapshot_lookback_hours`

- [ ] **Step 3: Write minimal implementation**

`AlertSettingsMixin` に追加:

```python
alert_snapshot_lookback_hours: int = Field(
    default=2,
    ge=1,
    le=168,
    description="AlertRule firing スナップショットの from_time を fired_at から遡る時間（時間単位）。",
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_alert_settings.py -v
```

Expected: PASS（全件）

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/settings.py tests/test_alert_settings.py
git commit -m "feat(settings): add alert_snapshot_lookback_hours

AlertRule 発火時に保存するスナップショットの遡り期間を設定可能にする。
"
```

---

### Task 2: スナップショット用 build_request 組み立て（純関数）

**Files:**
- Create: [`src/vcenter_event_assistant/services/incident_timeline_snapshot.py`](src/vcenter_event_assistant/services/incident_timeline_snapshot.py)
- Test: [`tests/test_incident_timeline_snapshot.py`](tests/test_incident_timeline_snapshot.py)

- [ ] **Step 1: Write the failing test**

`tests/test_incident_timeline_snapshot.py` 新規:

```python
from datetime import datetime, timezone, timedelta

from vcenter_event_assistant.services.incident_timeline_snapshot import (
    build_alert_rule_snapshot_build_request,
    slug_alert_context_key,
)


def test_slug_alert_context_key_normalizes_moid():
    assert slug_alert_context_key("host-1") == "host_1"


def test_build_alert_rule_snapshot_build_request_lookback():
    fired_at = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc)
    req = build_alert_rule_snapshot_build_request(
        fired_at=fired_at,
        to_time=now,
        lookback_hours=2,
    )
    assert req.from_time == fired_at - timedelta(hours=2)
    assert req.to_time == now
    assert req.include_period_metrics_cpu is True
    assert req.include_period_metrics_memory is True
    assert req.alert_top_n == 7
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py -v
```

Expected: FAIL — `ModuleNotFoundError` または import エラー

- [ ] **Step 3: Write minimal implementation**

`incident_timeline_snapshot.py`:

```python
from __future__ import annotations

import re
from datetime import datetime, timedelta

from vcenter_event_assistant.api.schemas.chat import IncidentTimelineBuildRequest

_CONTEXT_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug_alert_context_key(context_key: str) -> str:
    slug = _CONTEXT_SLUG_RE.sub("_", context_key.lower()).strip("_")
    return slug or "unknown"


def build_alert_rule_snapshot_build_request(
    *,
    fired_at: datetime,
    to_time: datetime,
    lookback_hours: int,
) -> IncidentTimelineBuildRequest:
    return IncidentTimelineBuildRequest(
        from_time=fired_at - timedelta(hours=lookback_hours),
        to_time=to_time,
        include_period_metrics_cpu=True,
        include_period_metrics_memory=True,
        alert_top_n=7,
        top_notable_min_score=1,
    )


def format_alert_rule_trigger_id(*, rule_id: int, context_key: str) -> str:
    return f"alert_rule_{rule_id}_{slug_alert_context_key(context_key)}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/incident_timeline_snapshot.py tests/test_incident_timeline_snapshot.py
git commit -m "feat(snapshot): add alert-rule build_request helpers

AlertRule 発火スナップショット用の期間と trigger_id 生成を純関数で固定する。
"
```

---

### Task 3: DB 永続化（firing 1 件・重複スキップ）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/incident_timeline_snapshot.py`](src/vcenter_event_assistant/services/incident_timeline_snapshot.py)
- Test: [`tests/test_incident_timeline_snapshot.py`](tests/test_incident_timeline_snapshot.py)

- [ ] **Step 1: Write the failing test**

同ファイルに追加:

```python
import pytest
from sqlalchemy import select

from vcenter_event_assistant.db.models import AlertRule, AlertState, IncidentTimelineManualSnapshot
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.incident_timeline_snapshot import (
    persist_alert_rule_firing_snapshot,
)


@pytest.mark.asyncio
async def test_persist_alert_rule_firing_snapshot_inserts_once():
    fired_at = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    to_time = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    rule = AlertRule(name="CPU High", rule_type="metric_threshold", config={"metric_key": "cpu", "threshold": 90})
    state = AlertState(rule_id=1, state="firing", context_key="host-1", fired_at=fired_at)

    async with session_scope() as session:
        session.add(rule)
        await session.flush()
        state.rule_id = rule.id
        await persist_alert_rule_firing_snapshot(
            session=session,
            rule=rule,
            state=state,
            details="Metric cpu reached 95",
            to_time=to_time,
            lookback_hours=2,
        )
        await persist_alert_rule_firing_snapshot(
            session=session,
            rule=rule,
            state=state,
            details="Metric cpu reached 95",
            to_time=to_time,
            lookback_hours=2,
        )
        await session.commit()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        rows = res.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.trigger_id == "alert_rule_1_host_1"
        assert row.trigger_evidence["trigger_type"] == "alert_rule"
        assert row.operator_note.startswith("自動スナップショット:")
        assert row.build_request_payload["include_period_metrics_cpu"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py::test_persist_alert_rule_firing_snapshot_inserts_once -v
```

Expected: FAIL — `persist_alert_rule_firing_snapshot` not defined

- [ ] **Step 3: Write minimal implementation**

`incident_timeline_snapshot.py` に追加（import: `and_`, `select`, `IncidentTimelineManualSnapshot`, `get_settings` または `lookback_hours` 引数で渡す — テストでは引数渡し済み）:

```python
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import AlertRule, AlertState, IncidentTimelineManualSnapshot


async def persist_alert_rule_firing_snapshot(
    *,
    session: AsyncSession,
    rule: AlertRule,
    state: AlertState,
    details: str,
    to_time: datetime,
    lookback_hours: int,
) -> None:
    if state.state != "firing":
        return
    fired_at = state.fired_at
    if fired_at.tzinfo is None:
        fired_at = fired_at.replace(tzinfo=timezone.utc)
    build_body = build_alert_rule_snapshot_build_request(
        fired_at=fired_at,
        to_time=to_time,
        lookback_hours=lookback_hours,
    )
    trigger_id = format_alert_rule_trigger_id(rule_id=rule.id, context_key=state.context_key)
    normalized_timestamp = fired_at.astimezone(timezone.utc)
    exists = await session.execute(
        select(IncidentTimelineManualSnapshot.id).where(
            and_(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
                IncidentTimelineManualSnapshot.from_time == build_body.from_time,
                IncidentTimelineManualSnapshot.to_time == build_body.to_time,
                IncidentTimelineManualSnapshot.timestamp_utc == normalized_timestamp,
                IncidentTimelineManualSnapshot.trigger_id == trigger_id,
            )
        )
    )
    if exists.scalar_one_or_none() is not None:
        return
    session.add(
        IncidentTimelineManualSnapshot(
            from_time=build_body.from_time,
            to_time=build_body.to_time,
            timestamp_utc=normalized_timestamp,
            operator_note=f"自動スナップショット: {rule.name} ({state.context_key})",
            build_request_payload=build_body.model_dump(mode="json", by_alias=True, exclude_none=True),
            snapshot_kind="auto",
            trigger_id=trigger_id,
            trigger_evidence={
                "trigger_type": "alert_rule",
                "rule_id": rule.id,
                "rule_name": rule.name,
                "context_key": state.context_key,
                "state": state.state,
                "fired_at_utc": normalized_timestamp.isoformat().replace("+00:00", "Z"),
                "details": details,
            },
        )
    )
```

（`timezone` を import に追加）

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/incident_timeline_snapshot.py tests/test_incident_timeline_snapshot.py
git commit -m "feat(snapshot): persist alert-rule firing snapshots

重複キーで二重 INSERT を防ぎ、build_request_payload を保存する。
"
```

---

### Task 4: タイムライン POST から暗黙保存を削除

**Files:**
- Modify: [`src/vcenter_event_assistant/api/routes/incident_timeline.py`](src/vcenter_event_assistant/api/routes/incident_timeline.py)
- Modify: [`tests/test_incident_timeline_api.py`](tests/test_incident_timeline_api.py)

- [ ] **Step 1: Write the failing test**

`test_post_incident_timeline_persists_auto_trigger_snapshots` を **置換**（関数名も変更可）:

```python
@pytest.mark.asyncio
async def test_post_incident_timeline_does_not_persist_auto_trigger_snapshots(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ... 既存 test_post_incident_timeline_persists_auto_trigger_snapshots と同じ monkeypatch フィクスチャ ...
    r = await client.post(
        "/api/incident-timeline",
        json=_request_body(include_period_metrics_cpu=True),
    )
    assert r.status_code == 200

    list_r = await client.get(
        "/api/incident-timeline/snapshots/manual",
        params={"limit": 20, "offset": 0},
    )
    assert list_r.status_code == 200
    auto_items = [
        item for item in list_r.json()["items"] if item.get("snapshot_kind") == "auto"
    ]
    assert auto_items == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_incident_timeline_api.py::test_post_incident_timeline_does_not_persist_auto_trigger_snapshots -v
```

Expected: FAIL — `len(auto_items) >= 3` 相当（現状は auto が残る）

- [ ] **Step 3: Write minimal implementation**

[`incident_timeline.py`](src/vcenter_event_assistant/api/routes/incident_timeline.py):

1. `post_incident_timeline` から `await _persist_auto_trigger_snapshots(...)` 行を削除
2. 未使用になる `_persist_auto_trigger_snapshots` 関数全体を削除（import の整理: `and_`, `IncidentTimelineEntry` 等が他で未使用なら削除）

```python
@router.post("", response_model=IncidentTimelinePayload)
async def post_incident_timeline(
    body: IncidentTimelineBuildRequest,
    session: AsyncSession = Depends(get_session),
) -> IncidentTimelinePayload:
    return await build_incident_timeline_payload(session, body)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_incident_timeline_api.py::test_post_incident_timeline_does_not_persist_auto_trigger_snapshots -v
uv run pytest tests/test_incident_timeline_api.py -v
```

Expected: PASS（既存の auto trigger **表示** テスト `test_post_incident_timeline_auto_triggers_are_emitted_as_alerts` はそのまま緑のまま）

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/api/routes/incident_timeline.py tests/test_incident_timeline_api.py
git commit -m "fix(timeline): stop implicit auto snapshots on POST

タイムライン生成は JSON 返却のみとし、明示保存 API に委ねる。
"
```

---

### Task 5: AlertEvaluator から firing 時に保存

**Files:**
- Modify: [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py)
- Test: [`tests/test_incident_timeline_snapshot.py`](tests/test_incident_timeline_snapshot.py)

- [ ] **Step 1: Write the failing test**

`tests/test_incident_timeline_snapshot.py` に追加（メールのみモック、`_notify` は実装を通す）:

```python
from unittest.mock import AsyncMock, patch

from vcenter_event_assistant.db.models import EventRecord, VCenter
from vcenter_event_assistant.services.alert_eval import AlertEvaluator


@pytest.mark.asyncio
async def test_evaluate_event_score_firing_persists_auto_snapshot():
    async with session_scope() as session:
        vc = VCenter(name="vc_snap", host="vc_snap", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="High Score Snapshot",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        event = EventRecord(
            vcenter_id=vc.id,
            occurred_at=datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            event_type="HostConnectionLostEvent",
            vmware_key=99,
            notable_score=70,
        )
        session.add(event)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        rows = res.scalars().all()
        assert len(rows) == 1
        assert rows[0].trigger_id.startswith("alert_rule_")
        assert rows[0].trigger_evidence["trigger_type"] == "alert_rule"


@pytest.mark.asyncio
async def test_evaluate_event_score_resolution_does_not_add_snapshot():
    async with session_scope() as session:
        vc = VCenter(name="vc_res", host="vc_res", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Cooldown Snapshot",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key="SomeEvent",
            fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        session.add(state)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator.email_channel, "notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        res = await session.execute(
            select(IncidentTimelineManualSnapshot).where(
                IncidentTimelineManualSnapshot.snapshot_kind == "auto",
            )
        )
        assert len(res.scalars().all()) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py::test_evaluate_event_score_firing_persists_auto_snapshot -v
```

Expected: FAIL — `len(rows) == 0`

- [ ] **Step 3: Write minimal implementation**

[`alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py) の `_notify` 先頭付近:

```python
from datetime import datetime, timezone
from vcenter_event_assistant.settings import get_settings
from vcenter_event_assistant.services.incident_timeline_snapshot import persist_alert_rule_firing_snapshot
from vcenter_event_assistant.db.session import session_scope

async def _notify(self, rule: AlertRule, state: AlertState, extra_context: dict) -> None:
    settings = get_settings()
    if state.state == "firing":
        async with session_scope() as session:
            await persist_alert_rule_firing_snapshot(
                session=session,
                rule=rule,
                state=state,
                details=str(extra_context.get("details", "")),
                to_time=datetime.now(timezone.utc),
                lookback_hours=settings.alert_snapshot_lookback_hours,
            )
            await session.commit()
    # 既存: render, email, AlertHistory ...
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_incident_timeline_snapshot.py tests/test_alert_eval_events.py tests/test_alert_eval_metrics.py -v
```

Expected: PASS。既存 `test_evaluate_*` は `_notify` を patch しているため影響なし。

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_incident_timeline_snapshot.py
git commit -m "feat(alerts): save timeline snapshot on rule firing

AlertEvaluator の firing 通知時にのみ auto スナップショットを永続化する。
"
```

---

### Task 6: 設計ドキュメントと回帰

**Files:**
- Create: [`docs/superpowers/specs/2026-05-22-alert-driven-snapshot-design.md`](docs/superpowers/specs/2026-05-22-alert-driven-snapshot-design.md)

- [ ] **Step 1:** spec に Goal / 非目標 / trigger_id 契約 / データフロー図を記載（日本語）

- [ ] **Step 2: Run full related tests**

```bash
uv run pytest tests/test_incident_timeline_api.py tests/test_incident_timeline_snapshot.py tests/test_alert_eval_events.py tests/test_alert_eval_metrics.py tests/test_alert_settings.py -v
```

Expected: 全 PASS

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-22-alert-driven-snapshot-design.md
git commit -m "docs: add alert-driven snapshot design spec

タイムライン生成と AlertRule 発火のスナップショット責務を文書化する。
"
```

---

## Spec セルフレビュー（プラン作成時）

| 要件 | タスク |
|------|--------|
| POST タイムラインで暗黙保存しない | Task 4 |
| AlertRule firing で auto 保存 | Task 3, 5 |
| 明示 manual POST 維持 | 非変更（既存テストで回帰） |
| resolved で保存しない | Task 3 `state != firing`、Task 5 resolution テスト |
| 重複 INSERT 防止 | Task 3 |
| lookback 設定 | Task 1 |

プレースホルダー: なし。

---

## 手動確認（オプション）

1. タイムラインタブで「タイムラインを生成」→ スナップショット一覧に **新規 auto が出ない**
2. 「スナップショットを保存」→ **manual** が 1 件増える
3. AlertRule 条件を満たすデータで `evaluate_alerts` 実行（または待機）→ 一覧に **auto**（`alert_rule_*`）が 1 件増える

---

## リスク

- **`_notify` 内の二重 `session_scope`:** 既存パターンと同様。トランザクション境界は Task 5 のテストで確認済みとする。
- **メール失敗時もスナップショットが残る:** 通知失敗より調査用保存を優先（現状の AlertHistory と同様に通知と独立）。
