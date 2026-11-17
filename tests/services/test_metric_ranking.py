"""query_top_metric_hosts の vCenter の絞り込み（Issue #310）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vcenter_event_assistant.db.models import MetricSample, VCenter
from vcenter_event_assistant.db.session import session_scope
from vcenter_event_assistant.services.metric_ranking import query_top_metric_hosts

KEY = "host.cpu.usage_pct"
FROM = datetime(2026, 3, 22, 0, 0, 0, tzinfo=timezone.utc)
TO = FROM + timedelta(hours=24)


async def _add_vcenter(session: AsyncSession) -> uuid.UUID:
    vid = uuid.uuid4()
    session.add(VCenter(id=vid, name=f"vc-{vid.hex[:6]}", host="h", port=443, username="u", password="p"))
    await session.flush()
    return vid


def _sample(vid: uuid.UUID, moid: str, at: datetime, value: float) -> MetricSample:
    return MetricSample(
        vcenter_id=vid,
        sampled_at=at,
        entity_type="HostSystem",
        entity_moid=moid,
        entity_name=f"esxi-{moid}",
        metric_key=KEY,
        value=value,
    )


@pytest.mark.asyncio
async def test_without_vcenter_includes_hosts_of_every_vcenter() -> None:
    """vCenter 未指定では、すべての vCenter のホストからピークの高い順に選ぶ。同じ moid も vCenter ごとに別。"""
    async with session_scope() as session:
        v1 = await _add_vcenter(session)
        v2 = await _add_vcenter(session)
        session.add_all(
            [
                _sample(v1, "host-1", FROM + timedelta(hours=1), 50.0),
                _sample(v1, "host-1", FROM + timedelta(hours=2), 70.0),
                _sample(v2, "host-1", FROM + timedelta(hours=1), 90.0),
                _sample(v2, "host-2", FROM + timedelta(hours=3), 60.0),
                # 期間外
                _sample(v1, "host-3", TO, 99.0),
            ]
        )
        await session.flush()
        rows = await query_top_metric_hosts(session, KEY, FROM, TO)
        only_v1 = await query_top_metric_hosts(session, KEY, FROM, TO, vcenter_id=v1)
    assert [(r.vcenter_id, r.entity_moid, r.value) for r in rows] == [
        (v2, "host-1", 90.0),
        (v1, "host-1", 70.0),
        (v2, "host-2", 60.0),
    ]
    assert [(r.vcenter_id, r.entity_moid, r.value) for r in only_v1] == [(v1, "host-1", 70.0)]


@pytest.mark.asyncio
async def test_without_any_vcenter_returns_empty() -> None:
    """vCenter が 1 つも無い（サンプルも無い）ときは空で返す。"""
    async with session_scope() as session:
        assert await query_top_metric_hosts(session, KEY, FROM, TO) == []
        assert await query_top_metric_hosts(session, KEY, FROM) == []
