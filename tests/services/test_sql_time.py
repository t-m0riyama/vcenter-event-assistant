"""sql_time のエポック秒・バケット番号の式のテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite

from vcenter_event_assistant.db.models import MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.sql_time import (
    bucket_index_expr,
    epoch_seconds_expr,
    truncate_to_second,
)

T0 = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)


async def _insert_samples(times: list[datetime]) -> None:
    vid = uuid.uuid4()
    async with session_scope() as session:
        session.add(
            VCenter(id=vid, name="vc", host="h", port=443, username="u", password="p", is_enabled=True)
        )
        for i, t in enumerate(times):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=t,
                    entity_type="HostSystem",
                    entity_moid=f"host-{i}",
                    entity_name=f"esxi-{i}",
                    metric_key="host.cpu.usage_pct",
                    value=1.0,
                )
            )


def test_truncate_to_second_drops_microseconds_and_keeps_utc() -> None:
    dt = datetime(2026, 3, 22, 0, 0, 0, 900_000, tzinfo=timezone.utc)
    assert truncate_to_second(dt) == datetime(2026, 3, 22, tzinfo=timezone.utc)
    naive = datetime(2026, 3, 22, 0, 0, 1, 500)
    assert truncate_to_second(naive) == datetime(2026, 3, 22, 0, 0, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_epoch_seconds_truncates_sub_second_on_sqlite() -> None:
    """``14:59.9996`` は丸めずに切り捨てる（SQLite のバージョン差を吸収する）。"""
    t = T0 + timedelta(minutes=14, seconds=59, microseconds=999_600)
    await _insert_samples([t])
    async with session_scope() as session:
        dialect = session.get_bind().dialect.name
        expr = epoch_seconds_expr(MetricSample.sampled_at, dialect)
        got = (await session.execute(select(expr))).scalar_one()
    assert got == int(T0.timestamp()) + 14 * 60 + 59


@pytest.mark.asyncio
async def test_bucket_index_starts_at_from_and_splits_on_boundary() -> None:
    times = [
        T0,
        T0 + timedelta(minutes=14, seconds=59, microseconds=999_600),
        T0 + timedelta(minutes=15),
        T0 + timedelta(minutes=31),
    ]
    await _insert_samples(times)
    async with session_scope() as session:
        dialect = session.get_bind().dialect.name
        bidx = bucket_index_expr(
            MetricSample.sampled_at, dialect, from_epoch=int(T0.timestamp()), bucket_sec=900
        )
        rows = (
            await session.execute(select(MetricSample.entity_moid, bidx).order_by(MetricSample.entity_moid))
        ).all()
    assert [int(b) for _, b in rows] == [0, 0, 1, 2]


def test_bucket_index_uses_integer_division_on_both_dialects() -> None:
    for dialect_name, dialect in (("postgresql", postgresql.dialect()), ("sqlite", sqlite.dialect())):
        bidx = bucket_index_expr(MetricSample.sampled_at, dialect_name, from_epoch=100, bucket_sec=900)
        sql = str(select(func.max(bidx)).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
        # SQLAlchemy 2.0 の ``//`` は、整数どうしなら PostgreSQL では ``/``、SQLite では ``/`` に
        # 落ちる（どちらも整数除算）。真の除算に変わると FLOAT への CAST が入る。
        assert "FLOAT" not in sql.upper()
        assert "BIGINT" in sql.upper()
