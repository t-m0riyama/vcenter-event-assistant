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


@pytest.mark.asyncio
async def test_metric_keys_distinct_sorted_and_scoped_by_vcenter(client: AsyncClient) -> None:
    r1 = await client.post(
        "/api/vcenters",
        json={
            "name": "vc-a",
            "host": "a.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    r2 = await client.post(
        "/api/vcenters",
        json={
            "name": "vc-b",
            "host": "b.example",
            "port": 443,
            "username": "u",
            "password": "p",
            "is_enabled": True,
        },
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    vid_a = uuid.UUID(r1.json()["id"])
    vid_b = uuid.UUID(r2.json()["id"])
    base = datetime.now(timezone.utc)

    async with session_scope() as session:
        session.add(
            MetricSample(
                vcenter_id=vid_a,
                sampled_at=base,
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name="h1",
                metric_key="host.cpu.usage_pct",
                value=1.0,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid_a,
                sampled_at=base + timedelta(seconds=1),
                entity_type="HostSystem",
                entity_moid="m1",
                entity_name="h1",
                metric_key="host.mem.usage_pct",
                value=2.0,
            )
        )
        session.add(
            MetricSample(
                vcenter_id=vid_b,
                sampled_at=base + timedelta(seconds=2),
                entity_type="HostSystem",
                entity_moid="m2",
                entity_name="h2",
                metric_key="host.mem.usage_pct",
                value=3.0,
            )
        )

    resp_all = await client.get("/api/metrics/keys")
    assert resp_all.status_code == 200
    assert resp_all.json()["metric_keys"] == ["host.cpu.usage_pct", "host.mem.usage_pct"]

    resp_a = await client.get(f"/api/metrics/keys?vcenter_id={vid_a}")
    assert resp_a.status_code == 200
    assert resp_a.json()["metric_keys"] == ["host.cpu.usage_pct", "host.mem.usage_pct"]

    resp_b = await client.get(f"/api/metrics/keys?vcenter_id={vid_b}")
    assert resp_b.status_code == 200
    assert resp_b.json()["metric_keys"] == ["host.mem.usage_pct"]


@pytest.mark.asyncio
async def test_metric_keys_empty_when_no_samples(client: AsyncClient) -> None:
    resp = await client.get("/api/metrics/keys")
    assert resp.status_code == 200
    assert resp.json()["metric_keys"] == []
