# イベントスコアアラート発火修正 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `event_score` アラートがイベント一覧と同じ `notable_score` で初回 firing し、全期間スキャンによる古いイベントの誤発火を防ぐ。評価ウィンドウは環境変数 `ALERT_EVENT_EVAL_LOOKBACK_HOURS` のみ（ルールごとの lookback は追加しない）。

**Architecture:** 設定は [`AlertSettingsMixin`](src/vcenter_event_assistant/settings.py) に `alert_event_eval_lookback_hours` を追加。評価ロジックは純関数モジュール [`alert_eval_event_score_config.py`](src/vcenter_event_assistant/services/alert_eval_event_score_config.py) で config 正規化とウィンドウ開始時刻を計算し、[`alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py) の `_evaluate_event_score` が DB クエリに `occurred_at >= window_start` を適用する。TDD: 純関数テスト → 統合テストの順。

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, SQLAlchemy async, Pydantic Settings, APScheduler

---

## Git / ブランチ方針

- **`main` 上での直接実装・直接コミットは行わない**（ユーザー明示時のみ例外）。
- **実装開始前:** Superpowers **`using-git-worktrees`** で隔離ワークツリーを用意する。
  - 推奨ブランチ: `feature/event-score-alert-fix`
  - 推奨パス: `.worktrees/feature-event-score-alert-fix/`
- **コミット前:** `git branch --show-current` / `git rev-parse --show-toplevel` / `pwd` を短文報告。
- **`main` へのマージ・`git push origin main`** はユーザー明示がない限り行わない。

詳細: [docs/snippets/git-branch-policy-for-plans.md](../snippets/git-branch-policy-for-plans.md)

---

## 背景

| 現象 | 原因候補 |
|------|----------|
| イベント一覧で閾値超過なのに通知履歴が空 | `config.threshold` が文字列だと `>=` で TypeError → ルール評価が例外ログのみ |
| 古いイベントで無関係に firing | `_evaluate_event_score` が **全期間**から閾値以上の最新 1 件を取得 |
| メトリクスは発火する | 同一 `evaluate_all` 内で metric 分岐のみ成功している |

**ユーザー確定要件:**

- 評価ウィンドウは **`ALERT_EVENT_EVAL_LOOKBACK_HOURS` のみ**（アラートルール `config` に lookback は持たない）
- フロントの AlertRulesPanel に lookback 入力は **追加しない**

### 仕様バグ（プラン Task 5 初版 — レビューで検出すべきだった）

| 項目 | 問題 |
|------|------|
| 分類 | **通知利用者に不利益な仕様変更**（コード欠陥ではないが、プラン/spec レビューで必ず止める） |
| 初版 Task 5 | `context_key = str(latest_event.id)` → メール **Resource** が `177353` 等の数字のみになり、従来の **`vim.event.UserLoginSessionEvent` 等の種別表示**が失われる |
| デザインとの関係 | [`2026-04-23-alert-notification-design.md`](../plans/2026-04-23-alert-notification-design.md) は `context_key` を「event_type や MOID 等」とのみ定義。**event_score で ID 固定はデザイン未承認** |
| **確定修正方針（ユーザー）** | **`context_key` は `latest_event.event_type` に戻す**。再通知（`occurred_at` が `fired_at` より新しいとき）は維持 |

**プラン/spec レビュー・チェックリスト（以降必須）:**

- [ ] メール件名・本文テンプレの `{{ context_key }}` の**利用者向け表示**が変わらないか
- [ ] [`alert_firing.txt.j2`](../../src/vcenter_event_assistant/templates/alert_firing.txt.j2) の 1 行目 `Rule ... - {{ context_key }}` を実サンプルで確認
- [ ] 元デザインの「継続中は何もしない」と再通知ポリシーの差分を明示し、連続メールが許容か確認

---

## ファイル構成

| ファイル | 責務 |
|----------|------|
| **Create** [`src/vcenter_event_assistant/services/alert_eval_event_score_config.py`](src/vcenter_event_assistant/services/alert_eval_event_score_config.py) | `EventScoreEvalConfig`、threshold/cooldown 正規化、ウィンドウ開始時刻 |
| **Modify** [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py) | `_evaluate_event_score` のウィンドウ付きクエリ・再通知・resolved・DEBUG ログ |
| **Modify** [`src/vcenter_event_assistant/settings.py`](src/vcenter_event_assistant/settings.py) | `alert_event_eval_lookback_hours` |
| **Create** [`tests/test_alert_eval_event_score_config.py`](tests/test_alert_eval_event_score_config.py) | 純関数 TDD |
| **Modify** [`tests/test_alert_eval_events.py`](tests/test_alert_eval_events.py) | ウィンドウ・文字列 threshold・再通知 |
| **Modify** [`tests/test_alert_settings.py`](tests/test_alert_settings.py) | env 既定・上書き |
| **Modify** [`docs/backend.md`](docs/backend.md) | event_score トラブルシュート |
| **Modify** [`.env.example`](.env.example) | `ALERT_EVENT_EVAL_LOOKBACK_HOURS` |

**スコープ外:** フロント変更、`AlertRule.config.lookback_hours`、手動 `POST /api/alerts/evaluate`

---

### Task 0: ワークツリーとベースライン

- [ ] **Step 1:** worktree 作成（`using-git-worktrees`）

```bash
# リポジトリ直下で（手順は skill に従う）
git worktree add .worktrees/feature-event-score-alert-fix -b feature/event-score-alert-fix
cd .worktrees/feature-event-score-alert-fix
```

- [ ] **Step 2:** ベースライン

```bash
uv run pytest tests/test_alert_eval_events.py tests/test_alert_settings.py tests/test_alert_eval_logging.py -q
```

Expected: PASS（既存 2 event テストは Task 5 で assertion 更新後も緑になるよう順序を守る）

---

### Task 1: Settings — `ALERT_EVENT_EVAL_LOOKBACK_HOURS`

**Files:**
- Modify: [`src/vcenter_event_assistant/settings.py`](src/vcenter_event_assistant/settings.py)（`AlertSettingsMixin` 内、`alert_snapshot_lookback_hours` の直後）
- Modify: [`tests/test_alert_settings.py`](tests/test_alert_settings.py)
- Modify: [`.env.example`](.env.example)

- [ ] **Step 1: Write the failing test**

`tests/test_alert_settings.py` に追加:

```python
def test_alert_event_eval_lookback_hours_default():
    settings = Settings()
    assert settings.alert_event_eval_lookback_hours == 1


def test_alert_event_eval_lookback_hours_env_override(monkeypatch):
    monkeypatch.setenv("ALERT_EVENT_EVAL_LOOKBACK_HOURS", "6")
    settings = Settings()
    assert settings.alert_event_eval_lookback_hours == 6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_alert_settings.py::test_alert_event_eval_lookback_hours_default -v
```

Expected: FAIL — `Settings` has no attribute `alert_event_eval_lookback_hours`

- [ ] **Step 3: Write minimal implementation**

`src/vcenter_event_assistant/settings.py` の `AlertSettingsMixin`:

```python
    alert_event_eval_lookback_hours: int = Field(
        default=1,
        ge=1,
        le=168,
        description=(
            "event_score アラート評価ウィンドウ（時間）。"
            "occurred_at がこの時間より古いイベントは判定に使わない。"
        ),
    )
```

`.env.example` の末尾付近に追加:

```bash
# --- Alert evaluation ---
# ALERT_EVAL_INTERVAL_SECONDS=60
# event_score: 判定に使うイベントの最大遡り（時間）。全ルール共通。再起動で反映。
# ALERT_EVENT_EVAL_LOOKBACK_HOURS=1
# firing スナップショットの遡り（別パラメータ）: ALERT_SNAPSHOT_LOOKBACK_HOURS=2
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_alert_settings.py::test_alert_event_eval_lookback_hours_default tests/test_alert_settings.py::test_alert_event_eval_lookback_hours_env_override -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/settings.py tests/test_alert_settings.py .env.example
git commit -m "feat(settings): add ALERT_EVENT_EVAL_LOOKBACK_HOURS

event_score アラートの評価ウィンドウを環境変数で指定できる。
"
```

---

### Task 2: 純関数 — config 正規化（TDD）

**Files:**
- Create: [`src/vcenter_event_assistant/services/alert_eval_event_score_config.py`](src/vcenter_event_assistant/services/alert_eval_event_score_config.py)
- Create: [`tests/test_alert_eval_event_score_config.py`](tests/test_alert_eval_event_score_config.py)

- [ ] **Step 1: Write the failing tests**

`tests/test_alert_eval_event_score_config.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vcenter_event_assistant.services.alert_eval_event_score_config import (
    EventScoreEvalConfig,
    event_eval_window_start,
    parse_event_score_rule_config,
)


def test_parse_event_score_rule_config_accepts_string_threshold():
    cfg = parse_event_score_rule_config({"threshold": "60", "cooldown_minutes": "5"})
    assert cfg == EventScoreEvalConfig(threshold=60, cooldown_minutes=5)


def test_parse_event_score_rule_config_rejects_invalid_threshold():
    assert parse_event_score_rule_config({"threshold": "high"}) is None


def test_parse_event_score_rule_config_defaults_cooldown():
    cfg = parse_event_score_rule_config({"threshold": 70})
    assert cfg == EventScoreEvalConfig(threshold=70, cooldown_minutes=10)


def test_event_eval_window_start_subtracts_hours():
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    start = event_eval_window_start(now=now, lookback_hours=6)
    assert start == now - timedelta(hours=6)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_alert_eval_event_score_config.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`src/vcenter_event_assistant/services/alert_eval_event_score_config.py`:

```python
"""event_score アラート評価用の純関数（DB 非依存）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class EventScoreEvalConfig:
    threshold: int
    cooldown_minutes: int


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_event_score_rule_config(raw: dict[str, Any]) -> EventScoreEvalConfig | None:
    """ルール config から threshold / cooldown を正規化。失敗時は None。"""
    legacy = raw.get("min_notable_score")
    threshold_raw = raw.get("threshold", legacy if legacy is not None else 60)
    threshold = _coerce_int(threshold_raw)
    if threshold is None or not 0 <= threshold <= 100:
        return None
    cooldown = _coerce_int(raw.get("cooldown_minutes"))
    if cooldown is None:
        cooldown = 10
    if cooldown < 1:
        return None
    return EventScoreEvalConfig(threshold=threshold, cooldown_minutes=cooldown)


def event_eval_window_start(*, now: datetime, lookback_hours: int) -> datetime:
    """評価対象イベントの occurred_at 下限（UTC 想定）。"""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(hours=lookback_hours)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_alert_eval_event_score_config.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval_event_score_config.py tests/test_alert_eval_event_score_config.py
git commit -m "feat(alerts): parse event_score rule config as pure functions

文字列 threshold を int に正規化し、テスト可能なヘルパに分離する。
"
```

---

### Task 3: 評価ウィンドウ — 古いイベントでは firing しない（RED→GREEN）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py)
- Modify: [`tests/test_alert_eval_events.py`](tests/test_alert_eval_events.py)

- [ ] **Step 1: Write the failing test**

`tests/test_alert_eval_events.py` に追加:

```python
from vcenter_event_assistant.settings import get_settings


@pytest.mark.asyncio
async def test_evaluate_event_score_ignores_high_score_outside_lookback_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALERT_EVENT_EVAL_LOOKBACK_HOURS", "2")
    get_settings.cache_clear()
    try:
        async with session_scope() as session:
            vc = VCenter(name="vc_window", host="vc_window", username="u", password="p")
            session.add(vc)
            await session.flush()
            rule = AlertRule(
                name="Window Test",
                rule_type="event_score",
                config={"threshold": 60, "cooldown_minutes": 5},
            )
            session.add(rule)
            session.add(
                EventRecord(
                    vcenter_id=vc.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(hours=5),
                    event_type="OldEvent",
                    vmware_key=1,
                    notable_score=90,
                )
            )
            await session.flush()
            rule_id = rule.id

        evaluator = AlertEvaluator()
        with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
            await evaluator.evaluate_all()
            mock_notify.assert_not_called()

        async with session_scope() as session:
            from sqlalchemy import select

            res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
            assert res.scalar_one_or_none() is None
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_ignores_high_score_outside_lookback_window -v
```

Expected: FAIL — `_notify` was called（現行は全期間から OldEvent を拾う）

- [ ] **Step 3: Implement window in `_evaluate_event_score`**

`alert_eval.py` 先頭に import 追加:

```python
from vcenter_event_assistant.services.alert_eval_event_score_config import (
    event_eval_window_start,
    parse_event_score_rule_config,
)
```

`_evaluate_event_score` を次の骨格に置き換え（**この Task では再通知・context_key 変更はまだ入れない** — 既存 firing 更新のみ）:

```python
    async def _evaluate_event_score(self, rule: AlertRule) -> tuple[int, int]:
        parsed = parse_event_score_rule_config(rule.config)
        if parsed is None:
            logger.warning("event_score rule=%s id=%s: invalid config", rule.name, rule.id)
            return 0, 0

        settings = get_settings()
        lookback_hours = settings.alert_event_eval_lookback_hours
        now = datetime.now(timezone.utc)
        window_start = event_eval_window_start(now=now, lookback_hours=lookback_hours)
        threshold = parsed.threshold
        cooldown_mins = parsed.cooldown_minutes
        firings = 0
        resolutions = 0

        async with session_scope() as session:
            res = await session.execute(
                select(EventRecord)
                .where(
                    EventRecord.notable_score >= threshold,
                    EventRecord.occurred_at >= window_start,
                )
                .order_by(desc(EventRecord.occurred_at))
                .limit(1)
            )
            latest_event = res.scalar_one_or_none()
            # ... 以降は既存の state 遷移ロジック（context_key はまだ event_type）...
```

DEBUG ログ（この Task で追加）:

```python
            logger.debug(
                "event_score rule=%s lookback_hours=%s window_start=%s qualifying_in_window=%s",
                rule.name,
                lookback_hours,
                window_start.isoformat(),
                latest_event is not None,
            )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_alert_eval_events.py -v
```

Expected: 新テスト PASS。既存 `test_evaluate_event_score_firing` / `resolution` も PASS（イベントは now 付近のまま）

- [ ] **Step 5: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_alert_eval_events.py
git commit -m "fix(alerts): limit event_score evaluation to lookback window

ALERT_EVENT_EVAL_LOOKBACK_HOURS より古い notable イベントは firing 対象外にする。
"
```

---

### Task 4: 文字列 threshold で評価が落ちない（RED→GREEN）

**Files:**
- Modify: [`tests/test_alert_eval_events.py`](tests/test_alert_eval_events.py)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_firing_with_string_threshold_in_config() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_str", host="vc_str", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="String Threshold",
            rule_type="event_score",
            config={"threshold": "60", "cooldown_minutes": 5},
        )
        session.add(rule)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=datetime.now(timezone.utc),
                event_type="Evt",
                vmware_key=2,
                notable_score=70,
            )
        )
        await session.flush()
        rule_id = rule.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        assert res.scalar_one().state == "firing"
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_firing_with_string_threshold_in_config -v
```

Expected: PASS（Task 2–3 で `parse_event_score_rule_config` 済みのため **即 PASS の場合はテストが既存挙動を固定できている** — 未実装なら FAIL のはず）

もし Task 3 前に実行して FAIL したら、Task 2 完了後に GREEN になることを確認。

- [ ] **Step 3: Commit**（テストのみ追加で RED だった場合）

```bash
git add tests/test_alert_eval_events.py
git commit -m "test(alerts): event_score accepts string threshold in config

インポート JSON の文字列 threshold で評価が例外にならないことを固定する。
"
```

---

### Task 5: 新規イベント再通知（`context_key` は **event_type** のまま）

**Files:**
- Modify: [`src/vcenter_event_assistant/services/alert_eval.py`](src/vcenter_event_assistant/services/alert_eval.py)
- Modify: [`tests/test_alert_eval_events.py`](tests/test_alert_eval_events.py)

**禁止:** `context_key = str(latest_event.id)`（仕様バグ。メール Resource が運用者に無意味な数字になる）

- [ ] **Step 1: firing テストは種別を期待**

`test_evaluate_event_score_firing`:

```python
        assert state.context_key == "HostConnectionLostEvent"  # latest_event.event_type
```

- [ ] **Step 2: Write the failing test for re-notify**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_renotifies_when_newer_qualifying_event_arrives() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re", host="vc_re", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        t_old = datetime.now(timezone.utc) - timedelta(minutes=30)
        t_new = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t_old,
                event_type="TypeA",
                vmware_key=10,
                notable_score=80,
            )
        )
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t_new,
                event_type="TypeB",
                vmware_key=11,
                notable_score=85,
            )
        )
        ev_new = session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t_new,
                event_type="TypeB",
                vmware_key=11,
                notable_score=85,
            )
        )
        # ↑ 重複追加を避ける: 1 件の new イベントだけ add し id を取得
```

**修正版（コピペ用・1 件の新イベント）:**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_renotifies_when_newer_qualifying_event_arrives() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re", host="vc_re", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        await session.flush()
        rule_id = rule.id
        t_old = datetime.now(timezone.utc) - timedelta(minutes=30)
        t_new = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t_old,
                event_type="TypeA",
                vmware_key=10,
                notable_score=80,
            )
        )
        ev_new = EventRecord(
            vcenter_id=vc.id,
            occurred_at=t_new,
            event_type="TypeB",
            vmware_key=11,
            notable_score=85,
        )
        session.add(ev_new)
        await session.flush()

        state = AlertState(
            rule_id=rule.id,
            state="firing",
            context_key=str(ev_new.id - 1),  # 意図的に別 id（旧 fired）
            fired_at=t_old,
        )
        session.add(state)
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1
        assert mock_notify.call_args[0][1].state == "firing"

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        st = res.scalar_one()
        assert st.fired_at == t_new
```

**より単純な再通知テスト（推奨）:** 最初の評価で firing → 2 件目 insert → 再評価で `_notify` 2 回。`context_key` は **新しいイベントの `event_type`**（下記 E2）。

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_renotifies_on_second_newer_event() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_re2", host="vc_re2", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Renotify2",
            rule_type="event_score",
            config={"threshold": 60, "cooldown_minutes": 30},
        )
        session.add(rule)
        t1 = datetime.now(timezone.utc) - timedelta(minutes=20)
        ev1 = EventRecord(
            vcenter_id=vc.id,
            occurred_at=t1,
            event_type="E1",
            vmware_key=1,
            notable_score=70,
        )
        session.add(ev1)
        await session.flush()
        rule_id = rule.id
        ev1_id = ev1.id

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock):
        await evaluator.evaluate_all()

    t2 = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_scope() as session:
        session.add(
            EventRecord(
                vcenter_id=vc.id,
                occurred_at=t2,
                event_type="E2",
                vmware_key=2,
                notable_score=75,
            )
        )
        await session.flush()

    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.call_count == 1

    async with session_scope() as session:
        from sqlalchemy import select

        res = await session.execute(select(AlertState).where(AlertState.rule_id == rule_id))
        st = res.scalar_one()
        assert st.state == "firing"
        assert st.fired_at == t2
        assert st.context_key == "E2"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_renotifies_on_second_newer_event -v
```

Expected: FAIL — 2 回目の `evaluate_all` で `_notify` が呼ばれない（現行は firing 中は fired_at 更新のみ）

- [ ] **Step 4: Implement re-notify and context_key**

`_evaluate_event_score` の `if latest_event:` 分岐で:

```python
                context_key = latest_event.event_type
                event_at = _as_utc(latest_event.occurred_at)
                should_notify = (
                    not current_state
                    or current_state.state == "resolved"
                    or event_at > _as_utc(current_state.fired_at)
                )
                if should_notify:
                    # new_state 作成 → _notify → firings = 1
                elif current_state and current_state.state == "firing":
                    current_state.fired_at = latest_event.occurred_at
                    current_state.context_key = context_key
```

ヘルパ `_as_utc(dt)` を同ファイルに小さく追加（naive UTC 補正、既存 resolved 分岐と同様）。

- [ ] **Step 5: Run all event tests**

```bash
uv run pytest tests/test_alert_eval_events.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/vcenter_event_assistant/services/alert_eval.py tests/test_alert_eval_events.py
git commit -m "fix(alerts): re-notify event_score when newer qualifying event appears

context_key は event_type のまま。occurred_at が fired_at より新しいとき firing 通知を再送する。
"
```

---

### Task 5b: 仕様バグ修正（既に event id で実装済みのブランチ向け）

**条件:** ワークツリーに `context_key = str(latest_event.id)` が入っている場合のみ実施。

- [ ] **Step 1:** `alert_eval.py` で `context_key = latest_event.event_type` に戻す（再通知ロジックは維持）
- [ ] **Step 2:** `test_evaluate_event_score_firing` 等の assertion を **種別名** に戻す
- [ ] **Step 3:** `docs/backend.md` の「`context_key` はイベント ID」を「**イベント種別（event_type）**」に修正
- [ ] **Step 4:** pytest 緑のうえコミット

```bash
git commit -m "fix(alerts): restore event_type as event_score context_key for notifications

メール Resource を運用者が識別できる種別名に戻す（仕様バグ修正）。
"
```

---

### Task 6: ウィンドウ内に該当なし + cooldown で resolved

**Files:**
- Modify: [`tests/test_alert_eval_events.py`](tests/test_alert_eval_events.py)

既存 `test_evaluate_event_score_resolution` は **DB に閾値以上イベントが無い**前提で resolved — ウィンドウ導入後も成立するはず。

- [ ] **Step 1: Write failing test — ウィンドウ外のみ高スコアでは resolved しない**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_does_not_resolve_when_only_old_events_above_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALERT_EVENT_EVAL_LOOKBACK_HOURS", "1")
    get_settings.cache_clear()
    try:
        async with session_scope() as session:
            vc = VCenter(name="vc_nores", host="vc_nores", username="u", password="p")
            session.add(vc)
            await session.flush()
            rule = AlertRule(
                name="NoResolveOld",
                rule_type="event_score",
                config={"threshold": 60, "cooldown_minutes": 1},
            )
            session.add(rule)
            await session.flush()
            rule_id = rule.id
            session.add(
                EventRecord(
                    vcenter_id=vc.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(hours=3),
                    event_type="Old",
                    vmware_key=1,
                    notable_score=99,
                )
            )
            session.add(
                AlertState(
                    rule_id=rule.id,
                    state="firing",
                    context_key="1",
                    fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
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
            assert res.scalar_one().state == "firing"
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_alert_eval_events.py::test_evaluate_event_score_does_not_resolve_when_only_old_events_above_threshold -v
```

Expected: PASS if Task 3 で「ウィンドウ内ゼロ＝latest_event None」かつ resolved は latest_event 無し時のみ — **現行 resolved ロジックは既に latest_event 無し + cooldown で resolve するため、古いイベントがあってもウィンドウ外なら latest_event は None → 誤って resolve してしまう可能性あり**

**実装要件:** resolved は **`latest_event is None`（ウィンドウ内に閾値以上なし）** のときのみ。全期間に高スコアがあってもウィンドウ外なら resolve **しない**。

Task 3 後の挙動: ウィンドウ内ゼロ → `latest_event is None` → 現行コードは cooldown で resolve してしまう → 上記テストは **FAIL する想定**。

- [ ] **Step 3: Fix resolution semantics**

resolved 条件に「直近ウィンドウ内に qualifying イベントが無い」ことを維持しつつ、**全期間に高スコアが残っていても** resolved しないよう、現行の `elif current_state and firing` は **`latest_event is None` のときだけ**入るので、テストが FAIL するなら **cooldown 開始基準を「ウィンドウ内最後の qualifying の時刻」** に変える必要はない — ユーザー要件は「古いイベントだけでは resolve も firing もしない」。

**修正:** `latest_event is None` かつ firing のとき、**ウィンドウ内に一度も qualifying が無い**状態が cooldown 継続したら resolve — これは現行のまま。問題は「ウィンドウ外にだけ高スコアがあると latest_event is None になり、cooldown で resolve」→ ユーザーは「まだインフラに高スコアイベントが DB にあるので resolved にしたくない」可能性。

プラン確定: **ウィンドウ内に qualifying が無い場合のみ resolved 候補**（現行の latest_event None）。テスト `does_not_resolve_when_only_old_events` は **firing のまま** を期待 — cooldown 経過後も resolve しないなら、追加条件「過去にウィンドウ内で qualifying があった場合は fired_at から cooldown」が必要。

**YAGNI 簡略版（本プラン採用）:** ウィンドウ内に qualifying が無い + cooldown 超過 → **resolved**（古い DB 行は無視）。テスト名の意図を「誤って **新規 firing** しない」に寄せると、上記テストは firing 維持で PASS。resolve テストは既存の「ウィンドウ内に低スコアのみ」ケースを追加:

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_resolves_when_no_qualifying_in_window() -> None:
    async with session_scope() as session:
        vc = VCenter(name="vc_res_win", host="vc_res_win", username="u", password="p")
        session.add(vc)
        await session.flush()
        rule = AlertRule(
            name="Resolve Window",
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
                event_type="Low",
                vmware_key=1,
                notable_score=10,
            )
        )
        session.add(
            AlertState(
                rule_id=rule.id,
                state="firing",
                context_key="99",
                fired_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
        )
        await session.flush()

    evaluator = AlertEvaluator()
    with patch.object(evaluator, "_notify", new_callable=AsyncMock) as mock_notify:
        await evaluator.evaluate_all()
        assert mock_notify.called
        assert mock_notify.call_args[0][1].state == "resolved"
```

- [ ] **Step 4: Run tests and commit**

```bash
uv run pytest tests/test_alert_eval_events.py -v
```

```bash
git add tests/test_alert_eval_events.py
git commit -m "test(alerts): event_score resolution uses in-window qualifying only

ウィンドウ内に閾値以上が無いときだけ cooldown 後に resolved になることを固定する。
"
```

---

### Task 7: 観測ログ（invalid config）

**Files:**
- Modify: [`tests/test_alert_eval_logging.py`](tests/test_alert_eval_logging.py)

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_evaluate_event_score_invalid_config_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with session_scope() as session:
        rule = AlertRule(
            name="Bad Config",
            rule_type="event_score",
            is_enabled=True,
            config={"threshold": "not-a-number"},
        )
        session.add(rule)
        await session.flush()

    caplog.set_level(logging.WARNING, logger="vcenter_event_assistant.services.alert_eval")
    evaluator = AlertEvaluator()
    await evaluator.evaluate_all()
    messages = [r.message for r in caplog.records if r.name == "vcenter_event_assistant.services.alert_eval"]
    assert any("invalid config" in m for m in messages)
```

- [ ] **Step 2: Run test** — Task 3 で WARNING 実装済みなら PASS

```bash
uv run pytest tests/test_alert_eval_logging.py::test_evaluate_event_score_invalid_config_logs_warning -v
```

- [ ] **Step 3: Commit if test was added in this task**

```bash
git add tests/test_alert_eval_logging.py
git commit -m "test(alerts): log warning when event_score config is invalid
"
```

---

### Task 8: ドキュメント

**Files:**
- Modify: [`docs/backend.md`](docs/backend.md) §2.4「定期アラート評価」

- [ ] **Step 1:** 次の内容を追記（日本語）

- `event_score` 判定は `events.notable_score >= config.threshold` かつ `occurred_at >= now - ALERT_EVENT_EVAL_LOOKBACK_HOURS`
- 環境変数変更は **再起動**が必要
- `ALERT_SNAPSHOT_LOOKBACK_HOURS` とは別
- ルール `config` に lookback は **ない**（`threshold`, `cooldown_minutes` のみ）
- 通知履歴で発火確認。`Error evaluating rule` / `invalid config` ログ

- [ ] **Step 2: Commit**

```bash
git add docs/backend.md
git commit -m "docs: document event_score alert window env and troubleshooting
"
```

---

### Task 9: 最終検証

- [ ] **Step 1: Full pytest**

```bash
uv run pytest tests/test_alert_eval_event_score_config.py tests/test_alert_eval_events.py tests/test_alert_eval_logging.py tests/test_alert_eval_metrics.py tests/test_alert_settings.py -q
```

Expected: すべて PASS

- [ ] **Step 2: 運用チェックリスト（マージ後・手動）**

1. `.env` に `ALERT_EVENT_EVAL_LOOKBACK_HOURS=1`（必要なら変更）→ 再起動
2. `event_score` ルール有効、`threshold` が意図どおり
3. イベント一覧で `notable_score >= threshold` かつ **直近 n 時間内** の行がある
4. 1–2 分後、通知履歴に `firing`
5. ログ: `alert evaluation complete ... firings>=1`

---

## セルフレビュー（プラン作成時）

| 要件 | タスク |
|------|--------|
| env のみで lookback | Task 1, 3 |
| ルールごと lookback なし | スコープ外明記、フロントなし |
| 古いイベントで誤 firing 防止 | Task 3 テスト |
| 文字列 threshold | Task 2, 4 |
| 初回 firing / 再通知 | Task 4–5 |
| TDD 手順 | 各 Task RED→GREEN |
| プレースホルダーなし | コードブロック完備 |

---

## 実行オプション

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-event-score-alert-fix.md`.**

**1. Subagent-Driven（推奨）** — タスクごとにサブエージェント、タスク間でレビュー

**2. Inline Execution** — このセッションで `executing-plans` によりバッチ実行

**どちらで進めますか？**
