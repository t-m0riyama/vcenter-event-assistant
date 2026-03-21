"""Metrics API (total count + points)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import MetricSample
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_metrics_returns_total_and_respects_limit(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "m1",
            "host": "vc.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r.status_code == 201
    vid = uuid.UUID(r.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        for i in range(3):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=base + timedelta(seconds=i),
                    entity_type="HostSystem",
                    entity_moid=f"mo-{i}",
                    entity_name=f"host-{i}",
                    metric_key="host.cpu.usage_pct",
                    value=float(10 + i),
                )
            )

    q = (
        "/api/metrics?metric_key=host.cpu.usage_pct"
        f"&vcenter_id={vid}"
        "&limit=2"
    )
    resp = await client.get(q)
    assert resp.status_code == 200
    assert resp.headers.get("X-Total-Count") == "3"
    body = resp.json()
    assert body["total"] == 3
    assert len(body["points"]) == 2
    assert body["points"][0]["value"] == 10.0


@pytest.mark.asyncio
async def test_metrics_empty_total_zero(client: AsyncClient) -> None:
    resp = await client.get("/api/metrics?metric_key=host.cpu.usage_pct&limit=10")
    assert resp.status_code == 200
    assert resp.headers.get("X-Total-Count") == "0"
    body = resp.json()
    assert body["total"] == 0
    assert body["points"] == []
