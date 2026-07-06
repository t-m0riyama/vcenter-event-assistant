# Event Score Cooldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** イベントスコア型アラートをイベント種別ごとに追跡し、クールダウンを再通知間隔のみに使う。自動回復は廃止する。

**Architecture:** 評価ウィンドウ内の閾値以上イベントを `event_type` で集約し、`(rule_id, context_key)` 単位の `AlertState` と `last_notified_at` で再通知を間引く。`metric_threshold` は触らない。利用者向け `alerts.md` と開発者向け `backend.md` を同一 PR で更新する。

**Tech Stack:** Python 3.12+, SQLAlchemy 2 async, Alembic, pytest, pytest-asyncio, React (AlertRulesPanel 文言のみ)

**Spec:** [docs/superpowers/specs/2026-05-23-event-score-cooldown-design.md](../specs/2026-05-23-event-score-cooldown-design.md)

---

## Git / ブランチ方針

- **`main` 上での直接実装・直接コミットは行わない**（ユーザーが **`main` でよい**と明示した場合のみ例外）。
- 作業は **feature ブランチ**、または **`git worktree` による隔離ワークツリー**上で行う。
- **コード変更・コミットに入る前**に、読み取り専用のシェルで少なくとも次を実行し、作業報告の冒頭で短文共有する。
  - `git branch --show-current`（空なら detached の可能性）
  - `git rev-parse --show-toplevel`
  - 可能なら `pwd`（`.worktrees/...` かリポジトリ直下かの目安）
- **実装開始（Task 1 のコード編集前）**は Superpowers の **`using-git-worktrees`** に従い隔離ワークツリーを用意する。
  - 推奨ブランチ: `feature/event-score-cooldown`
  - 推奨パス: `.worktrees/feature-event-score-cooldown/`
  - 作成前に **`git check-ignore .worktrees/`** で誤追跡を防ぐ。
- **`main` へのマージ・`git push origin main`** はユーザーの明示がない限りエージェントから実行しない。

詳細: [docs/snippets/git-branch-policy-for-plans.md](../../snippets/git-branch-policy-for-plans.md)

---

## ファイル構成

| ファイル | 責務 |
|----------|------|
| **Create** `alembic/versions/k4l5m6n7o8p9_alert_state_last_notified_at.py` | `last_notified_at` 列、バックフィル、UNIQUE |
| **Modify** `src/vcenter_event_assistant/db/models.py` | `AlertState.last_notified_at` |
| **Modify** `src/vcenter_event_assistant/services/alert_eval_event_score_config.py` | 種別集約・通知判定の純関数 |
| **Modify** `src/vcenter_event_assistant/services/alert_eval.py` | `_evaluate_event_score` 種別ループ、自動回復削除 |
| **Modify** `tests/test_alert_eval_event_score_config.py` | 純関数テスト |
| **Modify** `tests/test_alert_eval_events.py` | 統合テスト（T1–T5、既存改修） |
| **Modify** `docs/user-guides/alerts.md` | 利用者向け正本 |
| **Modify** `docs/backend.md` | §2.4 `event_score` |
| **Modify** `frontend/src/panels/settings/AlertRulesPanel.tsx` | クールダウンラベル・hint |

---

### Task 0: ワークツリーとベースライン

**Skills:** `using-git-worktrees`

- [ ] **Step 1:** ワークツリー作成

```bash
cd /path/to/vcenter-event-assistant
git check-ignore -q .worktrees || echo "ensure .worktrees in .gitignore"
git worktree add .worktrees/feature-event-score-cooldown -b feature/event-score-cooldown
cd .worktrees/feature-event-score-cooldown
git branch --show-current && pwd
```

- [ ] **Step 2:** 現行テストが緑であることを確認

```bash
uv run pytest tests/test_alert_eval_events.py tests/test_alert_eval_event_score_config.py -q
```

Expected: 現行仕様どおり PASS（この後 RED に変える）

---

### Task 1: DB — `last_notified_at` と UNIQUE

**Files:**
- Create: `alembic/versions/k4l5m6n7o8p9_alert_state_last_notified_at.py`
- Modify: `src/vcenter_event_assistant/db/models.py`

- [ ] **Step 1: 重複行の有無を確認（手順）**

```bash
uv run python -c "
import asyncio
from sqlalchemy import select, func
from vcenter_event_assistant.db.models import AlertState
from vcenter_event_assistant.db.session import session_scope

async def main():
    async with session_scope() as s:
        q = select(AlertState.rule_id, AlertState.context_key, func.count()).group_by(
            AlertState.rule_id, AlertState.context_key
        ).having(func.count() > 1)
        rows = (await s.execute(q)).all()
        print('duplicates', len(rows))
        for r in rows[:10]:
            print(r)

asyncio.run(main())
"
```

Expected: `duplicates 0`（0 でなければマイグレーション前に手動整理）

- [ ] **Step 2: マイグレーション作成**

`down_revision = "j3k4l5m6n7o8"`（実行時 `uv run alembic heads` で再確認）

```python
"""alert_states: last_notified_at and unique rule_id+context_key

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k4l5m6n7o8p9"
down_revision: Union[str, Sequence[str], None] = "j3k4l5m6n7o8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert_states",
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE alert_states SET last_notified_at = fired_at WHERE last_notified_at IS NULL"
    )
    op.create_unique_constraint(
        "uq_alert_states_rule_id_context_key",
        "alert_states",
        ["rule_id", "context_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_alert_states_rule_id_context_key", "alert_states", type_="unique")
    op.drop_column("alert_states", "last_notified_at")
```

- [ ] **Step 3: モデルに列追加**

`AlertState` に追記:

```python
last_notified_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

- [ ] **Step 4: マイグレーション適用（開発 DB）**

```bash
uv run alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/k4l5m6n7o8p9_alert_state_last_notified_at.py src/vcenter_event_assistant/db/models.py
git commit -m "feat(db): add alert_states.last_notified_at and unique rule context"
```

---

### Task 2: 純関数 — 種別集約と再通知判定（TDD）

**Files:**
- Modify: `src/vcenter_event_assistant/services/alert_eval_event_score_config.py`
- Modify: `tests/test_alert_eval_event_score_config.py`

- [ ] **Step 1: 失敗するテストを追加**

`tests/test_alert_eval_event_score_config.py` に追加:

```python
from datetime import datetime, timezone, timedelta

from vcenter_event_assistant.services.alert_eval_event_score_config import (
    event_score_should_notify,
    merge_latest_qualifying_by_event_type,
)


def test_merge_latest_qualifying_by_event_type_keeps_max_occurred_at() -> None:
    base = datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc)
    rows = [
        ("vim.event.A", base),
        ("vim.event.A", base + timedelta(minutes=2)),
        ("vim.event.B", base + timedelta(minutes=1)),
    ]
    merged = merge_latest_qualifying_by_event_type(rows)
    assert merged == {
        "vim.event.A": base + timedelta(minutes=2),
        "vim.event.B": base + timedelta(minutes=1),
    }


def test_event_score_should_notify_initial_firing() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    assert event_score_should_notify(
        current_state=None,
        last_qualifying_at=now - timedelta(minutes=1),
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_false_within_cooldown() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    last_notified = now - timedelta(minutes=3)
    assert not event_score_should_notify(
        current_state="firing",
        last_notified_at=last_notified,
        last_qualifying_at=now,
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_true_after_cooldown() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    last_notified = now - timedelta(minutes=11)
    assert event_score_should_notify(
        current_state="firing",
        last_notified_at=last_notified,
        last_qualifying_at=now,
        now=now,
        cooldown_minutes=10,
    )


def test_event_score_should_notify_after_resolved() -> None:
    now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
    assert event_score_should_notify(
        current_state="resolved",
        last_notified_at=now - timedelta(hours=1),
        last_qualifying_at=now,
        now=now,
        cooldown_minutes=10,
    )
```

- [ ] **Step 2: RED を確認**

```bash
uv run pytest tests/test_alert_eval_event_score_config.py::test_merge_latest_qualifying_by_event_type_keeps_max_occurred_at -v
```

Expected: FAIL（`merge_latest_qualifying_by_event_type` / `event_score_should_notify` 未定義）

- [ ] **Step 3: 最小実装**

`alert_eval_event_score_config.py` に追加（型はプロジェクト慣習に合わせ調整可）:

```python
from typing import Literal


def merge_latest_qualifying_by_event_type(
    rows: list[tuple[str, datetime]],
) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for event_type, occurred_at in rows:
        prev = out.get(event_type)
        if prev is None or occurred_at > prev:
            out[event_type] = occurred_at
    return out


def event_score_should_notify(
    *,
    current_state: Literal["firing", "resolved"] | None,
    last_notified_at: datetime | None,
    last_qualifying_at: datetime,
    now: datetime,
    cooldown_minutes: int,
) -> bool:
    if current_state is None or current_state == "resolved":
        return True
    if last_notified_at is None:
        return True
    if now - last_notified_at >= timedelta(minutes=cooldown_minutes):
        return True
    return False
```

- [ ] **Step 4: GREEN**

```bash
uv run pytest tests/test_alert_eval_event_score_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval_event_score_config.py tests/test_alert_eval_event_score_config.py
git commit -m "feat(alerts): add event_score notify interval pure helpers"
```

---

### Task 3: 自動回復廃止（TDD）

**Files:**
- Modify: `tests/test_alert_eval_events.py`
- Modify: `src/vcenter_event_assistant/services/alert_eval.py`

- [ ] **Step 1: 既存解決テストを置き換え（RED 先に書く）**

`test_evaluate_event_score_resolution` を **削除**し、次を追加:

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_does_not_auto_resolve_when_no_qualifying_in_window() -> None:
    """イベントスコア型は沈黙でも自動回復しない（spec R4）。"""
    async with session_scope() as session:
        vc = VCenter(name="vc_no_auto_res", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="No Auto Resolve",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 5},
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                event_type="LowOnly",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="vim.event.WasFiring",
                fired_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        st = res.scalar_one()
        assert st.state == "firing"
        assert st.context_key == "vim.event.WasFiring"
```

`test_evaluate_event_score_resolves_when_no_qualifying_in_window` も **削除**（上記と重複）。

- [ ] **Step 2: RED**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_does_not_auto_resolve_when_no_qualifying_in_window -v
```

Expected: FAIL（まだ自動 resolved する）

- [ ] **Step 3: `_evaluate_event_score` から自動回復分岐を削除**

`elif current_state and current_state.state == "firing":` かつ `latest_event is None` の resolved ブロック（L148–165 相当）を **丸ごと削除**。

※ この時点ではまだ単一 `latest_event` ロジックのままでよい。次 Task で種別ループに置換。

- [ ] **Step 4: GREEN（当該テストのみ）**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_does_not_auto_resolve_when_no_qualifying_in_window -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_alert_eval_events.py src/vcenter_event_assistant/services/alert_eval.py
git commit -m "fix(alerts): disable event_score auto-resolve on silence"
```

---

### Task 4: 種別ごと評価と再通知間隔（TDD）

**Files:**
- Modify: `src/vcenter_event_assistant/services/alert_eval.py`
- Modify: `tests/test_alert_eval_events.py`

- [ ] **Step 1: クールダウン内再通知抑制テスト（RED）**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_suppresses_renotify_within_cooldown_same_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_cd", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Cooldown Interval",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 10},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t1,
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id
        vcenter_id = vc.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    t2 = datetime.now(timezone.utc) - timedelta(minutes=2)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=t2,
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        mock_notify.assert_not_called()
```

- [ ] **Step 2: RED 確認**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_suppresses_renotify_within_cooldown_same_type -v
```

Expected: FAIL（2回目も notify）

- [ ] **Step 3: `_evaluate_event_score` を種別ループ実装に置換**

要点（疑似コード — 実装時は `metric_threshold` の `states` 辞書パターンに合わせる）:

```python
# 1) window 内 threshold 以上を event_type, occurred_at で SELECT（ORDER BY 不要、全件）
# 2) merge_latest_qualifying_by_event_type(...)
# 3) select(AlertState).where(AlertState.rule_id == rule.id) -> dict[context_key, AlertState]
# 4) for event_type, last_at in merged.items():
#      current = states.get(event_type)
#      if event_score_should_notify(...):
#          create/replace AlertState(firing, fired_at=last_at, last_notified_at=now)
#          await _notify(...)
#      elif current and current.state == "firing":
#          current.fired_at = last_at  # 通知なし更新
# 5) 自動 resolved 分岐は無し
```

`_notify` 成功後に `last_notified_at` を state に保存するか、notify 直前に set して flush。

- [ ] **Step 4: 種別独立テスト追加**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_independent_state_per_event_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_ind", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Per Type",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        now = datetime.now(timezone.utc)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now - timedelta(minutes=5),
                event_type="vim.event.UserLoginSessionEvent",
                vmware_key=1,
                notable_score=70,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=now - timedelta(minutes=3),
                event_type="vim.event.UserLogoutSessionEvent",
                vmware_key=2,
                notable_score=80,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 2

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        states = {s.context_key: s for s in res.scalars().all()}
        assert set(states) == {
            "vim.event.UserLoginSessionEvent",
            "vim.event.UserLogoutSessionEvent",
        }
        assert all(s.state == "firing" for s in states.values())
```

- [ ] **Step 5: 既存テスト修正**

| テスト | 変更 |
|--------|------|
| `test_evaluate_event_score_firing` | `scalar_one()` → `scalars().all()` が1件であることは維持可 |
| `test_evaluate_event_score_renotifies_on_second_newer_event` | **別種別 E2** ではなく **同種別 E1** でクールダウン11分後に再通知するケースへ変更（`last_notified_at` を手動で過去にするか、2回 eval の間に sleep は使わない） |

`test_evaluate_event_score_renotifies_on_second_newer_event` 改修例:

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_renotifies_after_cooldown_same_type() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re_cd", host="h", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify After Cooldown",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 10},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t1,
                event_type="vim.event.E1",
                vmware_key=1,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id
        vcenter_id = vc.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    async with session_scope() as session:
        from sqlalchemy import select

        st = (
            await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        ).scalar_one()
        st.last_notified_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        await session.flush()

    t2 = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vcenter_id,
                occurred_at=t2,
                event_type="vim.event.E1",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1
```

- [ ] **Step 6: 全 alert eval テスト GREEN**

```bash
uv run pytest tests/test_alert_eval_events.py tests/test_alert_eval_event_score_config.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_alert_eval_events.py
git commit -m "feat(alerts): per-event-type event_score eval with notify cooldown"
```

---

### Task 5: 回帰 — メトリクス型

**Files:**
- Test: `tests/test_alert_eval_metrics.py`（既存）

- [ ] **Step 1: メトリクス評価テストを実行**

```bash
uv run pytest tests/test_alert_eval_metrics.py -v
```

Expected: すべて PASS（未変更のはず）

- [ ] **Step 2: 問題があれば修正して commit（必要時のみ）**

---

### Task 6: ドキュメントと UI 文言

**Files:**
- Modify: `docs/user-guides/alerts.md`
- Modify: `docs/backend.md`
- Modify: `frontend/src/panels/settings/AlertRulesPanel.tsx`

- [ ] **Step 1: `docs/user-guides/alerts.md`**

spec の「利用者向け — クールダウンの定義」節を反映。§4・§5・§8 を更新。メトリクスとの対比表を1つ追加。

- [ ] **Step 2: `docs/backend.md` §2.4**

`event_score` 箇条書きから自動回復の記述を削除し、種別独立・`last_notified_at`・再通知間隔・手動回復予定を追記。先頭の `user-guides/alerts.md` リンクは維持。

- [ ] **Step 3: `AlertRulesPanel.tsx`**

編集行ラベル例:

```tsx
<label>
  再通知間隔（分）
  <input
    ...
    aria-label={`${r.name} の再通知間隔（分）`}
    title="同じイベント種別が続く場合でも、メールはおおむねこの間隔で1通まで"
  />
</label>
```

新規作成フォームの `cooldown` 関連も同様（キー名 `cooldown_minutes` は維持）。

- [ ] **Step 4: Commit**

```bash
git add docs/user-guides/alerts.md docs/backend.md frontend/src/panels/settings/AlertRulesPanel.tsx
git commit -m "docs: event_score cooldown as notify interval, no auto-resolve"
```

---

### Task 7: 最終検証

- [ ] **Step 1: PR 前 ruff（`tests/` 変更時は必須）**

```bash
uv run ruff check tests/
# CI と同一にする場合
uv run ruff check src tests
```

- [ ] **Step 2: 関連 pytest 一式**

```bash
uv run pytest tests/test_alert_eval_events.py tests/test_alert_eval_event_score_config.py tests/test_alert_eval_metrics.py -v
```

- [ ] **Step 3: フロント（任意・文言のみ）**

```bash
cd frontend && npm run test -- --run src/panels/settings/AlertRulesPanel.test.tsx 2>/dev/null || true
```

- [ ] **Step 4: PR 準備**

ユーザー指示があるまで `git push` / `main` マージは行わない。

---

## Spec カバレッジ（セルフレビュー）

| 要件 | タスク |
|------|--------|
| R1 種別ごと状態 | Task 4 |
| R2 クールダウン=再通知間隔 | Task 2, 4, 6 |
| R3 継続時再送抑制 | Task 4 |
| R4 自動回復なし | Task 3 |
| R5 メトリクス不変 | Task 5 |
| R6 lookback 不変 | 既存 `test_evaluate_event_score_ignores_high_score_outside_lookback_window` 維持 |
| R7 alerts.md | Task 6 |
| R8 手動回復は別フェーズ | spec + Task 6 文言のみ |

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-event-score-cooldown.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — This session continues with `executing-plans`, batch execution with checkpoints

Which approach?
