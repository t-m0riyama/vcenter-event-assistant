"""複合インデックス（2-2）: 存在確認と EXPLAIN QUERY PLAN。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import get_engine, init_db, reset_db, session_scope

EVENTS_INDEX = "ix_events_vcenter_id_occurred_at"
METRICS_INDEX = "ix_metric_samples_vcenter_entity_metric_sampled"


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
