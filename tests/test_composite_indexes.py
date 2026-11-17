"""複合インデックス（2-2）: 存在確認と EXPLAIN QUERY PLAN。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Response
from sqlalchemy import event, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from vcenter_event_assistant.api.routes.metrics import list_metrics
from vcenter_event_assistant.db.models import AlertHistory, AlertRule, EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import get_engine, init_db, reset_db, session_scope
from vcenter_event_assistant.services.alerting.alert_eval import AlertEvaluator
from vcenter_event_assistant.services.chat.chat_period_metrics import (
    METRIC_CPU,
    METRIC_MEM,
    build_chat_period_metrics,
)
from vcenter_event_assistant.services.metric_ranking import query_top_metric_hosts
from vcenter_event_assistant.settings import get_settings

pytestmark = pytest.mark.real_db_init

EVENTS_INDEX = "ix_events_vcenter_id_occurred_at"
METRICS_INDEX = "ix_metric_samples_vcenter_entity_metric_sampled"
VCENTER_METRIC_INDEX = "ix_metric_samples_vcenter_metric_sampled_value"
ALERT_HISTORY_INDEX = "ix_alert_history_notified_at"


async def _index_names(engine: AsyncEngine, table: str) -> set[str]:
    async with engine.connect() as conn:

        def sync_read(sync_conn) -> set[str]:
            return {idx["name"] for idx in inspect(sync_conn).get_indexes(table)}

        return await conn.run_sync(sync_read)


async def _explain_plan(engine: AsyncEngine, sql: str, params: dict) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"), params)
        rows = result.fetchall()
    return "\n".join(str(row) for row in rows)


@pytest.fixture
async def seeded_engine() -> AsyncEngine:
    await reset_db()
    await init_db()
    engine = get_engine()
    vcenter_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        session.add(
            VCenter(
                id=vcenter_id,
                name="idx-test",
                host="vc.example",
                username="u",
                password="p",
            )
        )
        for i in range(200):
            session.add(
                EventRecord(
                    vcenter_id=vcenter_id,
                    occurred_at=now - timedelta(minutes=i),
                    event_type="com.vmware.test",
                    message=f"event-{i}",
                    vmware_key=10_000 + i,
                    notable_score=1,
                )
            )
            session.add(
                MetricSample(
                    vcenter_id=vcenter_id,
                    sampled_at=now - timedelta(minutes=i),
                    entity_type="HostSystem",
                    entity_moid=f"host-{i % 5}",
                    entity_name=f"esxi-{i % 5}",
                    metric_key="cpu.usage.average",
                    value=float(i % 100),
                )
            )
    yield engine
    await reset_db()


@pytest.mark.asyncio
async def test_composite_indexes_exist_after_init_db() -> None:
    await reset_db()
    await init_db()
    engine = get_engine()
    events_indexes = await _index_names(engine, "events")
    metrics_indexes = await _index_names(engine, "metric_samples")
    assert EVENTS_INDEX in events_indexes
    assert METRICS_INDEX in metrics_indexes
    await reset_db()


@pytest.mark.asyncio
async def test_events_list_query_uses_composite_index(seeded_engine: AsyncEngine) -> None:
    async with session_scope() as session:
        vcenter_id = (await session.execute(select(VCenter.id).limit(1))).scalar_one()

    from_time = datetime.now(timezone.utc) - timedelta(hours=24)
    to_time = datetime.now(timezone.utc)
    plan = await _explain_plan(
        seeded_engine,
        """
        SELECT id FROM events
        WHERE vcenter_id = :vcenter_id
          AND occurred_at >= :from_time
          AND occurred_at <= :to_time
        ORDER BY occurred_at DESC
        LIMIT 100
        """,
        {"vcenter_id": str(vcenter_id), "from_time": from_time, "to_time": to_time},
    )
    assert EVENTS_INDEX in plan


@pytest.mark.asyncio
async def test_metrics_list_query_uses_composite_index(seeded_engine: AsyncEngine) -> None:
    async with session_scope() as session:
        vcenter_id = (await session.execute(select(VCenter.id).limit(1))).scalar_one()

    from_time = datetime.now(timezone.utc) - timedelta(hours=24)
    to_time = datetime.now(timezone.utc)
    plan = await _explain_plan(
        seeded_engine,
        """
        SELECT id FROM metric_samples
        WHERE vcenter_id = :vcenter_id
          AND metric_key = :metric_key
          AND entity_moid = :entity_moid
          AND sampled_at >= :from_time
          AND sampled_at <= :to_time
        ORDER BY sampled_at ASC
        LIMIT 2000
        """,
        {
            "vcenter_id": str(vcenter_id),
            "metric_key": "cpu.usage.average",
            "entity_moid": "host-0",
            "from_time": from_time,
            "to_time": to_time,
        },
    )
    assert METRICS_INDEX in plan


@contextmanager
def _capture_metric_sample_selects(engine: AsyncEngine) -> Iterator[list[tuple[str, Any]]]:
    """実際に実行された metric_samples の SELECT 文と引数を記録する（Issue #310）。"""
    captured: list[tuple[str, Any]] = []

    def listener(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT") and "FROM metric_samples" in statement:
            captured.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", listener)
    try:
        yield captured
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)


async def _plans_of(engine: AsyncEngine, captured: list[tuple[str, Any]]) -> list[str]:
    plans: list[str] = []
    async with engine.connect() as conn:
        for statement, parameters in captured:
            rows = (await conn.exec_driver_sql(f"EXPLAIN QUERY PLAN {statement}", parameters)).fetchall()
            plans.append("\n".join(str(row) for row in rows))
    return plans


@pytest.fixture
async def two_vcenter_metric_engine() -> AsyncIterator[AsyncEngine]:
    """vCenter 2 つと、直近のサンプル（CPU・メモリ）を入れた DB。"""
    await reset_db()
    await init_db()
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        for n in range(2):
            vid = uuid.uuid4()
            session.add(VCenter(id=vid, name=f"plan-{n}", host=f"vc{n}.example", username="u", password="p"))
            await session.flush()
            for i in range(30):
                for key in (METRIC_CPU, METRIC_MEM):
                    session.add(
                        MetricSample(
                            vcenter_id=vid,
                            sampled_at=now - timedelta(minutes=i),
                            entity_type="HostSystem",
                            entity_moid=f"host-{i % 3}",
                            entity_name=f"esxi-{i % 3}",
                            metric_key=key,
                            value=float(i % 100),
                        )
                    )
    yield get_engine()
    await reset_db()


def _assert_uses_vcenter_metric_index(captured: list[tuple[str, Any]], plans: list[str]) -> None:
    assert captured, "metric_samples の SELECT が捕まっていない"
    for (statement, _), plan in zip(captured, plans, strict=True):
        assert f"COVERING INDEX {VCENTER_METRIC_INDEX}" in plan, f"{statement}\n---\n{plan}"
        assert "ix_metric_samples_metric_key" not in plan, f"{statement}\n---\n{plan}"


def _assert_outer_looks_up_by_rowid(captured: list[tuple[str, Any]], plans: list[str]) -> None:
    """副問い合わせの id で表を引く外側の select は、主キーで 1 行ずつ引く（索引の全体を読まない）。

    ヒントは内側の副問い合わせにだけ付ける。外側に付けると、この引き当てが索引の全体を読む計画に変わる。
    """
    for (statement, _), plan in zip(captured, plans, strict=True):
        assert "SEARCH metric_samples USING INTEGER PRIMARY KEY (rowid=?)" in plan, f"{statement}\n---\n{plan}"
        assert statement.count("INDEXED BY") == 1, statement


async def _first_vcenter_id() -> uuid.UUID:
    async with session_scope() as session:
        return (await session.execute(select(VCenter.id).order_by(VCenter.name).limit(1))).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_vcenter", [False, True], ids=["all_vcenters", "one_vcenter"])
async def test_chat_period_metrics_uses_vcenter_metric_index(
    two_vcenter_metric_engine: AsyncEngine,
    with_vcenter: bool,
) -> None:
    """チャットの集計は、vCenter の指定の有無とも、vCenter・指標・期間の被覆索引で範囲を読む（Issue #310・#334）。

    新しい SQLite（3.51.0 以降で確認）は統計が無いと UNIQUE 制約の自動索引を選ぶので、INDEXED BY で固定している。
    """
    vcenter_id = await _first_vcenter_id() if with_vcenter else None
    to_utc = datetime.now(timezone.utc)
    with _capture_metric_sample_selects(two_vcenter_metric_engine) as captured:
        async with session_scope() as session:
            await build_chat_period_metrics(
                session,
                to_utc - timedelta(hours=6),
                to_utc,
                vcenter_id=vcenter_id,
                include_cpu=True,
                include_memory=True,
                include_disk_io=False,
                include_network_io=False,
            )
    _assert_uses_vcenter_metric_index(captured, await _plans_of(two_vcenter_metric_engine, captured))


@pytest.mark.asyncio
async def test_top_metric_hosts_without_vcenter_uses_vcenter_metric_index(
    two_vcenter_metric_engine: AsyncEngine,
) -> None:
    """ダッシュボード・ダイジェストの上位ホストも、vCenter 未指定で被覆索引だけで副問い合わせを済ませる（Issue #310）。"""
    to_utc = datetime.now(timezone.utc)
    with _capture_metric_sample_selects(two_vcenter_metric_engine) as captured:
        async with session_scope() as session:
            await query_top_metric_hosts(session, METRIC_CPU, to_utc - timedelta(hours=24), to_utc)
    plans = await _plans_of(two_vcenter_metric_engine, captured)
    _assert_uses_vcenter_metric_index(captured, plans)
    _assert_outer_looks_up_by_rowid(captured, plans)


@pytest.mark.asyncio
async def test_metric_threshold_evaluation_uses_vcenter_metric_index(
    two_vcenter_metric_engine: AsyncEngine,
) -> None:
    """アラート評価の最新サンプルの問い合わせも、被覆索引だけで副問い合わせを済ませる（Issue #310）。"""
    async with session_scope() as session:
        session.add(
            AlertRule(
                name="plan-cpu",
                rule_type="metric_threshold",
                is_enabled=True,
                config={"metric_key": METRIC_CPU, "threshold": 90.0},
            )
        )
    evaluator = AlertEvaluator(get_settings())
    with patch.object(evaluator, "_enqueue_notification", new_callable=AsyncMock):
        with _capture_metric_sample_selects(two_vcenter_metric_engine) as captured:
            await evaluator.evaluate_all()
    plans = await _plans_of(two_vcenter_metric_engine, captured)
    _assert_uses_vcenter_metric_index(captured, plans)
    _assert_outer_looks_up_by_rowid(captured, plans)


async def _call_list_metrics(**kwargs: Any) -> None:
    """``list_metrics`` を関数として呼ぶ（Query の既定値を使わないよう、引数はすべて渡す）。"""
    params: dict[str, Any] = {
        "vcenter_id": None,
        "metric_key": METRIC_CPU,
        "from_time": None,
        "to_time": None,
        "entity_moid": None,
        "limit": 2000,
    }
    params.update(kwargs)
    async with session_scope() as session:
        await list_metrics(Response(), session, **params)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_vcenter", [False, True], ids=["all_vcenters", "one_vcenter"])
@pytest.mark.parametrize("ranged", [True, False], ids=["range", "no_range"])
async def test_metrics_list_uses_vcenter_metric_index(
    two_vcenter_metric_engine: AsyncEngine,
    ranged: bool,
    with_vcenter: bool,
) -> None:
    """メトリクス一覧 API は、vCenter の指定の有無とも、件数・一覧とも vCenter・指標・期間の索引で範囲を読む
    （Issue #324・#334）。

    一覧は表の列も返すので被覆索引にはならない（索引名だけを見る）。件数は索引だけで済む。
    """
    to_utc = datetime.now(timezone.utc)
    kwargs: dict[str, Any] = {"from_time": to_utc - timedelta(hours=24), "to_time": to_utc} if ranged else {}
    if with_vcenter:
        kwargs["vcenter_id"] = await _first_vcenter_id()
    with _capture_metric_sample_selects(two_vcenter_metric_engine) as captured:
        await _call_list_metrics(limit=10000 if ranged else 500, **kwargs)
    plans = await _plans_of(two_vcenter_metric_engine, captured)
    assert len(captured) == 2, captured  # 件数と一覧
    for (statement, _), plan in zip(captured, plans, strict=True):
        assert VCENTER_METRIC_INDEX in plan, f"{statement}\n---\n{plan}"
        assert "ix_metric_samples_metric_key" not in plan, f"{statement}\n---\n{plan}"
    count_plan = next(p for (s, _), p in zip(captured, plans, strict=True) if "count(" in s.lower())
    assert f"COVERING INDEX {VCENTER_METRIC_INDEX}" in count_plan, count_plan


@pytest.mark.asyncio
async def test_metrics_list_without_vcenter_by_entity_uses_entity_index(
    two_vcenter_metric_engine: AsyncEngine,
) -> None:
    """vCenter 未指定で対象（entity_moid）を指定したときは、vCenter・対象・指標・期間の索引を使う（Issue #324）。"""
    to_utc = datetime.now(timezone.utc)
    with _capture_metric_sample_selects(two_vcenter_metric_engine) as captured:
        await _call_list_metrics(
            from_time=to_utc - timedelta(hours=24), to_time=to_utc, entity_moid="host-0", limit=10000
        )
    plans = await _plans_of(two_vcenter_metric_engine, captured)
    assert len(captured) == 2, captured
    for (statement, _), plan in zip(captured, plans, strict=True):
        assert METRICS_INDEX in plan, f"{statement}\n---\n{plan}"
        assert "ix_metric_samples_metric_key" not in plan, f"{statement}\n---\n{plan}"
        assert "ix_metric_samples_entity_moid" not in plan, f"{statement}\n---\n{plan}"
        # 対象を指定したときは被覆索引に固定しない（対象・指標・期間で絞れる索引のほうが向く）
        assert "INDEXED BY" not in statement, statement


@pytest.mark.asyncio
async def test_alert_history_notified_at_index_matches_model() -> None:
    """マイグレーションで作ったインデックスが、モデルの定義（名前・列）と一致する。"""
    model_indexes = {
        idx.name: [c.name for c in idx.columns] for idx in AlertHistory.__table__.indexes
    }
    assert model_indexes[ALERT_HISTORY_INDEX] == ["notified_at"]

    await reset_db()
    await init_db()
    engine = get_engine()
    async with engine.connect() as conn:
        db_indexes = await conn.run_sync(
            lambda c: {i["name"]: i["column_names"] for i in inspect(c).get_indexes("alert_history")}
        )
    assert db_indexes[ALERT_HISTORY_INDEX] == ["notified_at"]
    await reset_db()


@pytest.mark.asyncio
async def test_alert_history_range_query_uses_notified_at_index() -> None:
    """notified_at の範囲で絞り notified_at, id の順に並べるクエリがインデックスを使う（保持期間の削除・一覧）。"""
    await reset_db()
    await init_db()
    now = datetime.now(timezone.utc)
    async with session_scope() as session:
        rule = AlertRule(name="idx-alert", rule_type="event_score", alert_level="warning", config={})
        session.add(rule)
        await session.flush()
        for i in range(200):
            session.add(
                AlertHistory(
                    rule_id=rule.id,
                    alert_level="warning",
                    state="firing",
                    context_key=f"E{i % 7}",
                    notified_at=now - timedelta(minutes=i),
                    channel="none",
                )
            )
    plan = await _explain_plan(
        get_engine(),
        """
        SELECT alert_history.id FROM alert_history
        JOIN alert_rules ON alert_rules.id = alert_history.rule_id
        WHERE alert_history.notified_at >= :from_time
          AND alert_history.notified_at < :to_time
        ORDER BY alert_history.notified_at, alert_history.id
        LIMIT 1001
        """,
        {"from_time": now - timedelta(hours=1), "to_time": now},
    )
    assert ALERT_HISTORY_INDEX in plan
    await reset_db()
