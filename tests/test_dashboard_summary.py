"""Dashboard summary API (high_cpu_hosts per-host dedupe)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.db.models import MetricSample
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
