"""イベント・メトリクス取り込み（ingestion）のユニットテスト。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import event, func, select

from vcenter_event_assistant.db.models import EventRecord, MetricSample, VCenter
from vcenter_event_assistant.db.session import get_engine, session_scope
from vcenter_event_assistant.services.ingestion import (
    ingest_events_for_vcenter,
    ingest_metrics_for_vcenter,
)


def _make_event_rows(count: int) -> list[dict]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "occurred_at": base,
            "event_type": "com.vmware.test.event",
            "message": f"msg-{i}",
            "severity": "warning",
            "user_name": None,
            "entity_name": "host-1",
            "entity_type": "HostSystem",
            "vmware_key": i,
            "chain_id": None,
        }
        for i in range(count)
    ]


def _listen_events_table_selects() -> tuple[list[str], object]:
    """取り込み中に ``events`` テーブルへ向けた SELECT を収集するリスナを登録する。"""

    captured: list[str] = []
    sync_engine = get_engine().sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        upper = statement.upper()
        if "SELECT" in upper and " EVENTS" in f" {upper} ":
            captured.append(statement)

    return captured, _capture


@pytest.mark.asyncio
async def test_ingest_events_burst_does_not_select_events_table() -> None:
    """1,000 件バースト取り込みで重複確認 SELECT を発行しない。"""
    normalized = _make_event_rows(1000)
    max_ts = datetime(2026, 1, 2, tzinfo=timezone.utc)

    async with session_scope() as session:
        vc = VCenter(
            id=uuid.uuid4(),
            name="ingest-burst",
            host="vc.example",
            username="u",
            password="p",
        )
        session.add(vc)
        await session.flush()
        vcenter_id = vc.id

    event_selects, listener = _listen_events_table_selects()
    sync_engine = get_engine().sync_engine

    try:
        with patch(
            "vcenter_event_assistant.services.ingestion.asyncio.to_thread",
            new=AsyncMock(return_value=(normalized, max_ts)),
        ):
            async with session_scope() as session:
                vc = await session.get(VCenter, vcenter_id)
                assert vc is not None
                inserted = await ingest_events_for_vcenter(session, vc)

        assert inserted == 1000
        assert event_selects == []

        with patch(
            "vcenter_event_assistant.services.ingestion.asyncio.to_thread",
            new=AsyncMock(return_value=(normalized, max_ts)),
        ):
            async with session_scope() as session:
                vc = await session.get(VCenter, vcenter_id)
                assert vc is not None
                inserted_dup = await ingest_events_for_vcenter(session, vc)

        assert inserted_dup == 0
        assert event_selects == []
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)

    async with session_scope() as session:
        cnt = await session.execute(select(func.count()).select_from(EventRecord))
    assert cnt.scalar() == 1000


@pytest.mark.asyncio
async def test_ingest_metrics_skips_duplicates_without_select() -> None:
    """メトリクス取り込みも ON CONFLICT で重複 SELECT を避ける。"""
    sampled_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "sampled_at": sampled_at,
            "entity_type": "HostSystem",
            "entity_moid": "host-1",
            "entity_name": "esxi-a",
            "metric_key": "host.cpu.usage_pct",
            "value": 42.0,
        }
    ]

    async with session_scope() as session:
        vc = VCenter(
            id=uuid.uuid4(),
            name="ingest-metrics",
            host="vc.example",
            username="u",
            password="p",
        )
        session.add(vc)
        await session.flush()
        vcenter_id = vc.id

    metric_selects: list[str] = []
    sync_engine = get_engine().sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _capture_metrics(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        upper = statement.upper()
        if "SELECT" in upper and " METRIC_SAMPLES" in f" {upper} ":
            metric_selects.append(statement)

    try:
        with patch(
            "vcenter_event_assistant.services.ingestion.asyncio.to_thread",
            new=AsyncMock(return_value=rows),
        ):
            async with session_scope() as session:
                vc = await session.get(VCenter, vcenter_id)
                assert vc is not None
                first = await ingest_metrics_for_vcenter(session, vc)
                second = await ingest_metrics_for_vcenter(session, vc)

        assert first == 1
        assert second == 0
        assert metric_selects == []
    finally:
        event.remove(sync_engine, "before_cursor_execute", _capture_metrics)

    async with session_scope() as session:
        cnt = await session.execute(select(func.count()).select_from(MetricSample))
    assert cnt.scalar() == 1
