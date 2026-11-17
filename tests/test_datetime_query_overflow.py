"""UTC に直すと範囲を外れる日時は 500 ではなく 422 になる（Issue #331）。"""

from __future__ import annotations

from datetime import timezone

import pytest
from httpx import AsyncClient

from vcenter_event_assistant.api.schemas.digests import DigestRunRequest

OVERFLOW_VALUES = ["0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-01:00"]
NORMAL_FROM = "2026-01-01T00:00:00Z"
NORMAL_TO = "2026-01-02T00:00:00Z"

# (ラベル, パス, 追加のクエリ)
ENDPOINTS = [
    ("events", "/api/events", {}),
    ("rate-series", "/api/events/rate-series", {"event_type": "VmPoweredOnEvent"}),
    ("logs", "/api/logs", {}),
    ("logs-export", "/api/logs/export.csv", {}),
    ("metrics", "/api/metrics", {"metric_key": "cpu"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", OVERFLOW_VALUES)
@pytest.mark.parametrize("field", ["from", "to"])
@pytest.mark.parametrize("path,extra", [(p, e) for _, p, e in ENDPOINTS], ids=[n for n, _, _ in ENDPOINTS])
async def test_overflow_datetime_query_is_422(
    client: AsyncClient, path: str, extra: dict, field: str, bad: str
) -> None:
    params = {"from": NORMAL_FROM, "to": NORMAL_TO, **extra, field: bad}
    r = await client.get(path, params=params)
    assert r.status_code == 422, r.text
    assert any(d["loc"] == ["query", field] for d in r.json()["detail"])


@pytest.mark.asyncio
async def test_rate_series_missing_from_is_422_missing(client: AsyncClient) -> None:
    r = await client.get(
        "/api/events/rate-series",
        params={"event_type": "VmPoweredOnEvent", "to": NORMAL_TO},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(d["loc"] == ["query", "from"] and d["type"] == "missing" for d in detail)


@pytest.mark.asyncio
async def test_rate_series_accepts_non_utc_offset(client: AsyncClient) -> None:
    r = await client.get(
        "/api/events/rate-series",
        params={
            "event_type": "VmPoweredOnEvent",
            "from": "2026-01-01T09:00:00+09:00",
            "to": "2026-01-01T10:00:00+09:00",
        },
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", OVERFLOW_VALUES)
async def test_digest_run_overflow_from_time_is_422(client: AsyncClient, bad: str) -> None:
    r = await client.post(
        "/api/digests/run",
        json={"kind": "daily", "from_time": bad, "to_time": NORMAL_TO},
    )
    assert r.status_code == 422, r.text
    assert any(d["loc"] == ["body", "from_time"] for d in r.json()["detail"])


def test_digest_run_request_mixes_naive_and_aware() -> None:
    req = DigestRunRequest.model_validate(
        {"from_time": "2026-01-01T00:00:00", "to_time": "2026-01-02T00:00:00Z"}
    )
    assert req.from_time is not None and req.to_time is not None
    assert req.from_time.tzinfo is timezone.utc
    assert req.to_time.tzinfo is timezone.utc
