"""L-7 alert rule config validation."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metric_threshold_requires_metric_key(client: AsyncClient) -> None:
    r = await client.post(
        "/api/alerts/rules",
        json={
            "name": "bad-metric",
            "rule_type": "metric_threshold",
            "alert_level": "warning",
            "config": {"threshold": 90},
        },
    )
    assert r.status_code == 422
