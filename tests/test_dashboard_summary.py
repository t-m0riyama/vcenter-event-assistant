"""Dashboard summary API (high_cpu_hosts / high_mem_hosts per-host dedupe)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import EventRecord, MetricSample
from vcenter_event_assistant.db.session import session_scope


@pytest.mark.asyncio
async def test_high_cpu_hosts_one_row_per_host_uses_peak_value(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-dedupe",
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
        for i, val in enumerate([20.0, 95.0, 50.0]):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=base + timedelta(seconds=i),
                    entity_type="HostSystem",
                    entity_moid="host-same",
                    entity_name="esxi-a",
                    metric_key="host.cpu.usage_pct",
                    value=val,
                )
            )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    hosts = resp.json()["high_cpu_hosts"]
    same_host_rows = [h for h in hosts if h["entity_moid"] == "host-same"]
    assert len(same_host_rows) == 1
    assert same_host_rows[0]["value"] == 95.0
    # JSON must mark UTC so browsers parse the instant correctly (not as local time).
    assert same_host_rows[0]["sampled_at"].endswith("Z")


@pytest.mark.asyncio
async def test_high_cpu_hosts_returns_at_most_ten_hosts(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-limit",
            "host": "vc2.example",
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
        for i in range(11):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=base + timedelta(seconds=i),
                    entity_type="HostSystem",
                    entity_moid=f"host-{i}",
                    entity_name=f"esxi-{i}",
                    metric_key="host.cpu.usage_pct",
                    value=float(90 - i),
                )
            )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    hosts = resp.json()["high_cpu_hosts"]
    assert len(hosts) == 10
    assert hosts[0]["value"] == 90.0
    assert hosts[-1]["value"] == 81.0


@pytest.mark.asyncio
async def test_high_mem_hosts_one_row_per_host_uses_peak_value(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-mem-dedupe",
            "host": "vc-mem.example",
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
        for i, val in enumerate([20.0, 95.0, 50.0]):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=base + timedelta(seconds=i),
                    entity_type="HostSystem",
                    entity_moid="host-same-mem",
                    entity_name="esxi-mem",
                    metric_key="host.mem.usage_pct",
                    value=val,
                )
            )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    hosts = resp.json()["high_mem_hosts"]
    same_host_rows = [h for h in hosts if h["entity_moid"] == "host-same-mem"]
    assert len(same_host_rows) == 1
    assert same_host_rows[0]["value"] == 95.0
    assert same_host_rows[0]["sampled_at"].endswith("Z")


@pytest.mark.asyncio
async def test_high_mem_hosts_returns_at_most_ten_hosts(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-mem-limit",
            "host": "vc-mem2.example",
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
        for i in range(11):
            session.add(
                MetricSample(
                    vcenter_id=vid,
                    sampled_at=base + timedelta(seconds=i),
                    entity_type="HostSystem",
                    entity_moid=f"host-mem-{i}",
                    entity_name=f"esxi-mem-{i}",
                    metric_key="host.mem.usage_pct",
                    value=float(90 - i),
                )
            )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    hosts = resp.json()["high_mem_hosts"]
    assert len(hosts) == 10
    assert hosts[0]["value"] == 90.0
    assert hosts[-1]["value"] == 81.0


@pytest.mark.asyncio
async def test_top_event_types_24h_orders_by_count_desc_and_excludes_stale(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-event-types",
            "host": "vc3.example",
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
        key = 0
        for _ in range(3):
            key += 1
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=base,
                    event_type="TypeA",
                    message="m",
                    vmware_key=key,
                    notable_score=0,
                )
            )
        for _ in range(2):
            key += 1
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=base,
                    event_type="TypeB",
                    message="m",
                    vmware_key=key,
                    notable_score=0,
                )
            )
        key += 1
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base,
                event_type="TypeC",
                message="m",
                vmware_key=key,
                notable_score=0,
            )
        )
        key += 1
        session.add(
            EventRecord(
                vcenter_id=vid,
                occurred_at=base - timedelta(hours=25),
                event_type="StaleType",
                message="old",
                vmware_key=key,
                notable_score=0,
            )
        )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    rows = body["top_event_types_24h"]
    assert [r["event_type"] for r in rows] == ["TypeA", "TypeB", "TypeC"]
    assert [r["event_count"] for r in rows] == [3, 2, 1]
    assert body["events_last_24h"] == 6


@pytest.mark.asyncio
async def test_top_event_types_24h_returns_at_most_ten_types(client: AsyncClient) -> None:
    r = await client.post(
        "/api/vcenters",
        json={
            "name": "dash-etype-cap",
            "host": "vc4.example",
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
        for i in range(11):
            session.add(
                EventRecord(
                    vcenter_id=vid,
                    occurred_at=base,
                    event_type=f"Distinct{i}",
                    message="m",
                    vmware_key=i + 1,
                    notable_score=0,
                )
            )

    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    rows = resp.json()["top_event_types_24h"]
    assert len(rows) == 10
    assert all(r["event_count"] == 1 for r in rows)
